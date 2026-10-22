# Glossary review rules — Cyberpunk 2077 Romanian fan translation

You review AI-drafted glossary entries (Beam / MiniMax) for a Romanian translation of Cyberpunk 2077 + Phantom
Liberty. The user does not want to review routine entries: accept what is right, fix what is clearly wrong, and
send to the user ONLY entries where a reasonable Romanian gamer could genuinely go either way.

## The user's rules (non-negotiable)
- Setting is 2077 Night City: modern, urban, tech, English-dominated megacity. Romanian must sound like young
  Romanian gamers / IT people talk today. **No archaisms, ever** (no bookish, folkloric, rural, old-fashioned words).
- **Some Romglish is good.** English street/tech words with Romanian morphology are welcome: "netrunnerii",
  "gig-ul", "BD-ul", "upgrade", "hack-uit". Hyphen before Romanian endings when the stem would be unclear
  (gig-ul, BD-ul, AV-ul).
- **Slang — what the user decided so far:**
  - choom/choomba stay fully English, forms included (user, 2026-10-22): choom, chooms, choomba, choombas —
    never choomul, choomii, choomi, choomilor, choomule, choom-ul.
  - KEEP English (identity words of Night City): choom (user's own call), gig, eddies, fixer, netrunner,
    ripperdoc, corpo, merc, BD/braindance, chrome (cyberware sense), cyberpsycho, nomad (RO: nomad/nomazi).
  - The user REJECTED keeping English for **gonk, preem, scav** ("sounds unnatural / wrong tone"). So insults,
    adjectives and interjections (gonk, preem, nova, delta, flatline as a verb…) should become natural, modern
    Romanian slang (e.g. gonk → "bou"/"fraier"/"tâmpit", preem → "beton"/"marfă"/"de top", nova → "tare"/
    "mișto", delta → "a o tăia"/"a se cara"). Pick the best, put alternatives in the comment.
- Names of people, nicknames, AIs, districts, venues, corporations, brands, product/weapon/vehicle models, gangs
  and organizations stay English (Arasaka, Militech, Tyger Claws, Voodoo Boys, NCPD, MaxTac, NetWatch, NUSA, FIA,
  Dogtown, Afterlife, Delamain…). A landmark with a plain-noun head translates only the head ("Arasaka Tower" →
  "Turnul Arasaka").
- UI labels / game mechanics: translate, short, consistent, like a professional Romanian game UI. The user has
  already accepted e.g. Ieșire, Ajutor, Granată, Aruncă, Ridică-te, Conversație arhivată, sec.
- Correct Romanian: ș/ț with comma below, ă â î; correct plurals (nomazi, fixeri, netrunneri); correct gender.
- No Polish anywhere (the drafts saw Polish reference lines; Polish sometimes leaks — always a fix).
- Profanity is not a glossary term.

## Lore facts (the drafts sometimes got these wrong)
Relic = Arasaka biochip with Johnny's engram (key term). Blackwall = NetWatch's barrier against rogue AIs.
Samurai = Johnny's band; Johnny calls V "Samurai". Soulkiller, Mikoshi, engram, construct. NUSA = New United
States of America (NOT South America). FIA = Federal Intelligence Agency. Barghest = Kurt Hansen's militia in
Dogtown (an armed group, not a product). Songbird = So Mi (netrunner). Reed = Solomon Reed (FIA). MaxTac = NCPD
anti-cyberpsycho unit. Trauma Team = armed private medics. Delamain = AI taxi company. Aldecaldos = nomad clan.
Scavs = organ-harvesting gangs. Breach (Breach Protocol) = netrunning minigame/quickhack.

## Your decision per entry
- `ok` — the proposal is right (most entries; names kept in English are almost always ok).
- `fixed` — clearly wrong and you know the right form: `correction` = the corrected Romanian form; `comment` =
  one short reason (in Romanian). Optionally `decision`/`type`/`plural`/`gender` if those were wrong too.
- `flagged` — genuinely debatable, the user should choose: `correction` = your recommended form, `comment` =
  the question + 1-2 alternatives, in Romanian, short. Use this sparingly (target: under 10% of entries).
- Entries with `rejected_as_noise: true`: the drafter said "not a glossary term". Usually right (ordinary words,
  UI verbs) → `ok`. If it IS a real term (a lore word, a name, a mechanic), use `fixed` with `correction` = the
  Romanian form and `type`/`decision` filled in.
- Variants (`variants` field) are folded into the entry; judge the entry as a whole.

Output: a JSON array `[{"term", "status", "correction", "comment", ...}]`, one object per entry, every entry
covered, `term` copied exactly.

## Already decided in wave 1 — stay consistent with these
Fixed: ARAKI → Araki; AVEDON → Avedon; Alive → În viață; Ammo → Muniție; Arasaka Corporation → Corporația Arasaka; Arasaka Guard → Gardian Arasaka; Armor → Armură; Assault → Asalt; Attribute Point → Punct de atribut; BAKER → Baker; BORA → Bora; BUSH → Bush; Basic → De bază; Black Ops Operative → Agent Black Ops; Blades → Lame; Blunt Weapons → Arme contondente; Bouncer → Bodyguard; Braindance → braindance; Buffer → Buffer; CAPITAN → El Capitan; CHELO → Chelo; CHOI → Choi; Camo → Camuflaj; Cause of Death → Cauza morții; Charge → Încărcare; City Hall → Primăria; Claw → Gheară; Contact → contact; Convoy → Convoi; Corpo → corpo; Crafting → Fabricare; Crafting Spec → schemă de fabricare; Crit Damage → Daune critice; DNA → ADN; Dashing → dash; Death's Head → cap-de-mort; Diagnostics → Diagnosticare; Drop Point → Punct de predare; Duration → Durată; EBM Petrochem Stadium → Stadionul EBM Petrochem; EDVARDS → Edvards; EKLAND → Ekland; EMP Grenade → Granată EMP; Evaluation → Evaluare; F-GX Frag Grenade → Granată de fragmentare F-GX; Fast Travel → Călătorie rapidă; Feet → Picioare; Fixer's Car → Mașina fixerului; Food → Mâncare; Fourth Corporate War → Al Patrulea Război Corporatist; GREENE → Greene; Gain XP → Câștigă XP; Ghost → Fantomă; HART → Hart; Hacking → Hacking; Handbrake → Frână de mână; Haven Clinic → Clinica Haven; Implant → Implant; Incapacitate → Imobilizează; Inhaler → Inhalator; JONES → JONES; Japan → Japonia; Junk → Vechituri; Junk Vendor → Vânzător de vechituri; KARELINA → Karelina; KNUTSON → Knutson; LEE → Lee; Launcher → Lansator; Legs → Picioare; Lethal → Letal; MAJOR → MAIOR; MAKI → Maki; MALDONADO → Maldonado; MULLER → Muller; Makeup → Machiaj; Mantis Blades → Mantis Blades; Max RAM → RAM maxim; Melee Weapon → Armă de corp la corp; Memorial Park → Parcul Memorial; Merc Needed → Se caută merc; Message Regina → Trimite-i mesaj Reginei; Mexico → Mexic; Mitigation → Atenuare; Mitigation Chance → Șansă de atenuare; Mitigation Strength → Putere de atenuare; Mod Slot → Slot pentru mod; Morning → Dimineață; NCPD Scanner → Scaner NCPD; NCPD Scanner Hustles → Activități de pe scanerul NCPD; NOVAK → Novak; Netrunner → netrunner; Night City Area Rapid → Night City Area Rapid Transit; North California → California de Nord; ORLOV → ORLOV; Objective → Obiectiv; Options → Opțiuni; Overclock → Overclock; PECK → PECK; PERLMAN → PERLMAN; Phantom Liberty → Phantom Liberty; Photo Mode → Mod foto; Ping → Ping; Pistols → Pistoale; Please wait → Vă rugăm să așteptați; Possible Actions → Acțiuni posibile; Pout → Bosumflat; President Myers → președinta Myers; Profile → Profil; Project Cynosure → Proiectul Cynosure; Quickhacking → Quickhacking; REY → Rey; REZNIKOV → Reznikov; RIGGI → RIGGI; ROY → Roy; Results → Rezultate; Revolvers → revolvere; SAKURA → Sakura; SERGEANT → sergent; SOS Merc Needed → SOS: Caut merc; Safeword → Cuvânt de siguranță; Security Guard → Agent de securitate; Shake → Strânge-i mâna; Shock → Șoc; Slaughterhouse → Slaughterhouse; Slows → Încetinește; Software → Software; Special Agent → Agent special; Spread → Dispersie; Stadium → Stadionul; Stamina Regen Rate → Rată de regenerare a staminei; Star → Steaua; Stare → Privește fix; Stealth → Furișare; Stun → amețire; Support → Suport; Suspected Organized Crime Activity → Suspiciune de crimă organizată; Thug → Bătăuș; Today's Body Lottery → Body Lottery de azi; Track → Urmărește; Unification War → Războiul Unificării; VACK → Vack; VASILIEVA → Vasilieva; Volume → Volum; WILSON → Wilson; WINSTON → Winston; Workshop → Atelier; delta → a o tăia; engram → engram; flatline → a lichida; flatlined → terminat (a termina pe cineva); jack → a se conecta (jack in) / a se deconecta (jack out); moxes → Mox; nova → mișto; ripper → ripper; scav → hienă; solo → solo; zero → a lichida; zeroed → a lichida

Still open for the user (use the recommended form provisionally, do not re-flag the same question for closely related terms unless needed): CHAR Incendiary Grenade → Granată incendiară CHAR; City of Dreams → Orașul Viselor; Cool → Calm; Cooldown → Timp de recuperare; Dash → Dash; Goon → Bătăuș; Guard → Gardian; Gun for Hire → Mercenar la comandă; Heavy → Greu; MOD → mod (pl. mod-uri); Merc → Merc; Neuromotor Development → Centrul pentru Dezvoltare Neuromotorie; Perk → Talent; Punk → Golan; Raven → Negru-corb; Rush → Impuls; SMG → SMG; Scavengers → Hienele; Security Room → Cameră de pază; Shotguns → shotgun-uri; Skill Shard → Shard de abilitate; Spot → Loc; Stamina → Stamină; Street Cred → Reputație; Street Kid → Street Kid; Tier → Treaptă; Tier 1 → Treapta 1; Tier 2 → Treapta 2; Tier 3 → Treapta 3; Tier 4 → Tier 4; Tier 5 → Tier 5; breach → spargere; chromed → chromat; lifepath → Origine
