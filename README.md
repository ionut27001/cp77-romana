# Cyberpunk 2077 — Traducere în limba română

Traducere neoficială, făcută de fani, a întregului text din **Cyberpunk 2077 + Phantom Liberty** (versiunea jocului 2.5):
subtitrări, dialoguri, meniuri, iteme, jurnal, mesaje, shard-uri. Vocea rămâne în engleză.

**Descarcă mod-ul:**
- Nexus Mods (instalare cu un click din Vortex): https://www.nexusmods.com/cyberpunk2077/mods/35648
- Meniul MODURI din joc (mod.io, PC și console): https://mod.io/g/cyberpunk-2077/m/cyberpunk-2077-traducere-in-limba-romana

Acest repository e locul unde **oricine poate corecta traducerea**: o replică ciudată, un termen tradus greșit,
un gen greșit pentru V. Corecturile acceptate intră în următoarea versiune a mod-ului.

## Cum ajuți

- **Ai găsit o greșeală, dar nu vrei să editezi fișiere?** Deschide un
  [Issue „Greșeală de traducere”](../../issues/new/choose): scrii unde apare, ce e greșit și ce ai propune.
  O captură de ecran ajută mult.
- **Vrei să corectezi direct?** Vezi [CONTRIBUTING.md](CONTRIBUTING.md): găsești replica în `translations/`, editezi
  câmpul `"ro"` și trimiți un Pull Request. Se poate face și din browser, fără să instalezi nimic.

## Ce e în repository

| Folder | Ce conține |
|---|---|
| `translations/` | Tot textul, câte un fișier JSON pentru fiecare fișier de localizare din joc: originalul (`en`) și traducerea (`ro`) |
| `glossary/glosar.csv` | Argoul și termenii din Night City și cum se traduc (choom rămâne choom, gonk → fraier...) |
| `glossary/termeni.csv` | Nume fixe: personaje, locuri, arme, cyberware, misiuni, traduse identic peste tot |
| `glossary/expresii.json` | Expresii de argou și înjurături, cu variantele românești naturale |
| `glossary/REGULI_DE_STIL.md` | Regulile de stil ale traducerii |
| `tools/check.py` | Verificarea automată rulată pe fiecare Pull Request |
| `pipeline/` | Scripturile cu care a fost făcută traducerea și construit mod-ul (pentru cine e curios) |

Textul din repository are diacritice. La construirea mod-ului ele sunt scoase, pentru că fontul jocului nu are
literele ș și ț.

## Cum a fost făcută

Traducerea a fost generată cu modele de limbaj AI (DeepSeek, Beam, Claude), ghidată de glosarul, lista de termeni
și regulile de stil de mai sus, revizuite manual, apoi editată și verificată în joc. Tocmai de aceea ajută orice
corectură venită de la oameni care joacă.

## Licență

Mod neoficial, fără legătură cu CD PROJEKT RED. Cyberpunk 2077 și textul original în engleză aparțin
CD PROJEKT RED și sunt folosite conform [Fan Content Guidelines](https://www.cdprojektred.com/en/fan-content).
Traducerea românească se distribuie sub [CC BY-NC-SA 4.0](LICENSE-translation.md), scripturile sub [MIT](LICENSE).
Detalii în [NOTICE.md](NOTICE.md).

---

**English:** unofficial, fan-made Romanian translation of Cyberpunk 2077 + Phantom Liberty (game 2.5). This repo holds
all the text (`translations/`, English + Romanian side by side) so anyone can suggest fixes through Issues or Pull
Requests; accepted fixes ship in the next mod release on Nexus Mods and mod.io. The translation was generated with AI
language models, guided by a hand-reviewed glossary and style rules, then edited and checked in-game.
