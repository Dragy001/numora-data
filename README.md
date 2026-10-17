# numora-data

Wyniki losowań Lotto, Lotto Plus, Mini Lotto, Eurojackpot, Ekstra Pensji, Ekstra Premii i Kaskady dla aplikacji **Numora**, aktualizowane codziennie przez akcję GitHub.

| Plik | Zawartość |
|---|---|
| `data/manifest.json` | ostatni numer i data losowania każdej gry, czas aktualizacji |
| `data/<gra>.csv` | pełna historia |
| `data/<gra>-recent.csv` | ostatnie 100 losowań |
| `data/prizes.json` | tabele wygranych 5 ostatnich losowań każdej gry i kumulacje Lotto/Eurojackpot (bez historii) |

Format CSV (bez nagłówka): `numer,DD.MM.RRRR,liczby…` — w Eurojackpocie 5 liczb głównych, potem 2 liczby euro.
Numeracja Eurojackpota jest oficjalna (jak na kuponach). W Ekstra Pensji i Ekstra Premii po 5 liczbach głównych jest liczba z puli 1–4.
Kaskada (12 z 24, dwa losowania dziennie) zaczyna się od losowania nr 628 — w archiwum brakuje nr 627.
Nowa gra: dopisz ją w `GAMES` w `scripts/update.py` i uruchom `python3 scripts/update.py --rebuild <gra>`.

Źródło nowych losowań: archiwum megalotto.pl (nieoficjalne). Skrypt `scripts/update.py` tylko dopisuje nowe
losowania po sprawdzeniu ciągłości numeracji, dat i zakresu liczb — historii nie przepisuje.
Dane mają charakter informacyjny; wiążące są wyniki publikowane przez Totalizator Sportowy.
