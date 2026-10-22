"""Minimal chat client shared by the pipeline scripts: Ollama (local/cloud models) and the DeepSeek API.

Models are named as Ollama models ("beam:cloud") or "deepseek:<model>" ("deepseek:deepseek-chat").
On HTTP 429 every thread using that provider backs off together (shared cooldown per provider) instead of each
one hammering the endpoint on its own.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

URL = "http://localhost:11434/api/chat"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "minimax-m3.1-flash:cloud"

_lock = threading.Lock()
_cooldown_until = {}  # provider -> time
_backoff = {}
stats = {"rate_limited": 0}


def deepseek_key():
    """The key from the environment, or from the user's registry (setx writes there; running apps miss it)."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, "DEEPSEEK_API_KEY")[0]
    except OSError:
        return None


def _wait_cooldown(provider):
    while True:
        with _lock:
            wait = _cooldown_until.get(provider, 0) - time.time()
        if wait <= 0:
            return
        time.sleep(min(wait, 5))


def _hit_429(provider):
    with _lock:
        stats["rate_limited"] += 1
        b = _backoff.get(provider, 15.0)
        if time.time() >= _cooldown_until.get(provider, 0):  # first thread to notice sets the pause
            _cooldown_until[provider] = time.time() + b
            _backoff[provider] = min(b * 2, 300)


def _ok(provider):
    with _lock:
        _backoff[provider] = max(15.0, _backoff.get(provider, 15.0) * 0.8)


PRICES = {  # $ per 1M tokens: input, cache write (5 min), cache read, output
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 2.50, 0.20, 10.00),
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-5": (2.00, 2.50, 0.20, 10.00),
    "claude-sonnet-4-6": (3.00, 3.75, 0.30, 15.00),
    "claude-haiku-4-5": (1.00, 1.25, 0.10, 5.00),
}
NO_EFFORT = {"claude-haiku-4-5"}  # effort is rejected on Haiku 4.5
usage = {}  # model -> token counters, for exact cost reporting
_claude = None


def anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, "ANTHROPIC_API_KEY")[0]
    except OSError:
        return None


# JSON shape of translate/polish answers; structured outputs make older models' JSON reliable
LINES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["t"], "properties": {"t": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "f", "m"],
                               "properties": {"id": {"type": "integer"}, "f": {"type": "string"},
                                              "m": {"type": "string"}}}}}}


def _claude_request(model, system, user, think, timeout, schema=None):
    """Claude via the official SDK (installed in D:\\cp77-ro\\tools\\pylib). `think` = effort level or None."""
    global _claude
    import sys
    if r"D:\cp77-ro\tools\pylib" not in sys.path:
        sys.path.insert(0, r"D:\cp77-ro\tools\pylib")
    import anthropic
    if _claude is None:
        _claude = anthropic.Anthropic(api_key=anthropic_key(), max_retries=5, timeout=timeout)
    oc = {"effort": think} if isinstance(think, str) and model not in NO_EFFORT else {}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}
    kw = {"output_config": oc} if oc else {}
    try:
        r = _claude.messages.create(
            model=model, max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}], **kw)
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
        raise RuntimeError(f"claude: {type(e).__name__}: {e}") from e
    u = r.usage
    with _lock:
        c = usage.setdefault(model, {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "calls": 0})
        c["input"] += u.input_tokens or 0
        c["cache_write"] += u.cache_creation_input_tokens or 0
        c["cache_read"] += u.cache_read_input_tokens or 0
        c["output"] += u.output_tokens or 0
        c["calls"] += 1
    if r.stop_reason == "refusal":
        raise RuntimeError("claude refused the batch")
    if r.stop_reason == "max_tokens":
        raise RuntimeError("claude hit max_tokens")
    text = next((b.text for b in r.content if b.type == "text"), "")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return text


def cost(model):
    """Exact $ spent on a Claude model so far in this process."""
    c, p = usage.get(model), PRICES.get(model)
    if not c or not p:
        return 0.0
    return (c["input"] * p[0] + c["cache_write"] * p[1] + c["cache_read"] * p[2] + c["output"] * p[3]) / 1e6


def _request(model, system, user, think, timeout, schema=None):
    if model.startswith("anthropic:"):
        return _claude_request(model.split(":", 1)[1], system, user, think, timeout, schema)
    if model.startswith("deepseek:"):
        key = deepseek_key()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        body = {"model": model.split(":", 1)[1], "temperature": 0.3, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if think:  # DeepSeek thinking mode; a string is the reasoning effort (low/medium/high)
            body["thinking"] = {"type": "enabled"}
            if isinstance(think, str):
                body["reasoning_effort"] = think
            body.pop("temperature")
        req = urllib.request.Request(DEEPSEEK_URL, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return d["choices"][0]["message"]["content"]
    body = {"model": model, "stream": False, "think": think, "format": "json", "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(d["error"])
    return d["message"]["content"]


def chat_json(system, user, think=False, retries=8, timeout=900, model=None, schema=None):
    """Send one chat request that must answer with a JSON object; returns the parsed object."""
    model = model or MODEL
    provider = model.split(":", 1)[0] if model.startswith(("deepseek:", "anthropic:")) else "ollama"
    last = None
    for attempt in range(retries):
        _wait_cooldown(provider)
        try:
            out = json.loads(_request(model, system, user, think, timeout, schema))
            _ok(provider)
            return out
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                _hit_429(provider)
            elif e.code in (401, 402, 403):
                raise RuntimeError(f"{provider} refused the request (HTTP {e.code}: bad key or no balance)") from e
            else:
                time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError, TimeoutError, KeyError, IndexError) as e:
            last = e
            if "is not set" in str(e):
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"LLM request failed after {retries} tries: {last}")
