# numora-data

Wyniki losowań Lotto, Mini Lotto i Eurojackpot dla aplikacji **Numora**, aktualizowane codziennie przez akcję GitHub.

| Plik | Zawartość |
|---|---|
| `data/manifest.json` | ostatni numer i data losowania każdej gry, czas aktualizacji |
| `data/<gra>.csv` | pełna historia |
| `data/<gra>-recent.csv` | ostatnie 100 losowań |

Format CSV (bez nagłówka): `numer,DD.MM.RRRR,liczby…` — w Eurojackpocie 5 liczb głównych, potem 2 liczby euro.
Numeracja Eurojackpota jest oficjalna (jak na kuponach).

Źródło nowych losowań: archiwum megalotto.pl (nieoficjalne). Skrypt `scripts/update.py` tylko dopisuje nowe
losowania po sprawdzeniu ciągłości numeracji, dat i zakresu liczb — historii nie przepisuje.
Dane mają charakter informacyjny; wiążące są wyniki publikowane przez Totalizator Sportowy.
