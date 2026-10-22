# Cum corectezi traducerea

## 1. Găsește replica

Toată traducerea e în `translations/`, cu aceeași structură ca fișierele jocului:

- `translations/base/...`: jocul de bază; `translations/ep1/...`: Phantom Liberty
- `onscreens/`: meniuri, iteme, arme, cyberware, jurnal, mesaje (fișierele mari sunt împărțite în bucăți
  `onscreens.001.json`, `onscreens.002.json`...)
- `subtitles/`: dialoguri și subtitrări, grupate pe misiuni (`quest/`), scene din oraș (`open_world/`), radio, TV...

Cel mai simplu: apasă `T` pe pagina repository-ului (sau folosește căutarea GitHub) și caută textul **în engleză**
sau o bucată din traducerea greșită.

## 2. Editează doar câmpul `"ro"`

Fiecare replică arată așa:

```json
{
 "key": 1993580195386544128,
 "en": "Ahoy, sea wolves!",
 "ro": "Ahoy, lupi de mare!"
}
```

- Schimbi **doar** textul din `"ro"` (și `"ro_m"`, dacă există: varianta când V e bărbat; `"ro"` e varianta pentru
  V femeie sau, unde nu contează genul, singura variantă).
- **Nu** schimba `"key"`, `"en"` sau `"depot"`.
- Păstrează exact tag-urile și variabilele din engleză: `{player_name}`, `<Rich ...>`, `<Input ...>`, `</>`, `\n`.
  Verificarea automată respinge replica dacă lipsesc sau apar în plus.
- Scrie **cu diacritice** (ă, â, î, ș, ț). Mod-ul le scoate singur la construire.

Din browser: deschizi fișierul pe GitHub, apeși creionul (Edit), modifici, apoi **Commit changes → Create a new branch
→ Propose changes**. GitHub face singur fork-ul și Pull Request-ul.

## 3. Regulile de stil, pe scurt

Detaliile sunt în [glossary/REGULI_DE_STIL.md](glossary/REGULI_DE_STIL.md).

- Româna vorbită de azi, din 2077, **fără arhaisme** și fără limbaj de manual.
- Romgleza din Night City rămâne: **choom** (cu forme englezești: choom / chooms, niciodată „choomul”), gig, eddies,
  fixer, netrunner, ripperdoc, corpo, BD.
- Insultele și argoul devin **argou românesc natural** (gonk → fraier / bou, preem → beton / marfă).
- Expresiile și înjurăturile se traduc **după sens**, cum ar zice un român, nu cuvânt cu cuvânt. Vezi
  [glossary/expresii.json](glossary/expresii.json).
- Numele de personaje, locuri, arme, cyberware și misiuni se scriu **exact** ca în
  [glossary/termeni.csv](glossary/termeni.csv). Dacă vrei să schimbi un termen fix, deschide întâi un Issue: el apare
  în sute de locuri și trebuie schimbat peste tot deodată.
- **Genul lui V** contează: replicile adresate lui V au variantă de feminin (`ro`) și de masculin (`ro_m`).
- Delamain vorbește formal (dumneavoastră).
- În interfață: scurt și clar, textul trebuie să încapă în chenar.

## 4. Pull Request-ul

- Un PR poate conține oricâte corecturi; descrie pe scurt ce ai schimbat și de ce.
- Verificarea automată (`tools/check.py`) rulează pe fiecare PR. O poți rula și local: `python tools/check.py`.
- Corecturile acceptate intră în următoarea versiune a mod-ului pe Nexus Mods și mod.io.

## Nu știi exact cum? Deschide un Issue

Template-ul „Greșeală de traducere” te întreabă tot ce trebuie. E perfect și pentru o singură replică.
