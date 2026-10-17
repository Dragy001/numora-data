"""
scripts/update.py — dopisuje nowe losowania do plików w data/ i odświeża pliki dla aplikacji Numora.

Uruchamiane codziennie przez akcję GitHub (.github/workflows/update.yml), ręcznie: python3 scripts/update.py

Pliki (bez nagłówka, przecinki, zera wiodące — ten sam format co w aplikacji):
    data/<gra>.csv          pełna historia, np. 7414,06.10.2026,08,26,27,35,42,46
    data/<gra>-recent.csv   ostatnie RECENT_COUNT losowań (aplikacja pobiera zwykle tylko ten mały plik)
    data/manifest.json      ostatni numer i data dla każdej gry — aplikacja sprawdza go przy starcie

Źródło nowych losowań: roczne archiwa megalotto.pl (nieoficjalne). Historii NIE przepisujemy — dopisujemy tylko
losowania o numerach większych niż ostatni w pliku, po sprawdzeniu ciągłości numeracji, dat i liczb.
"""

# json — manifest; re — wyrażenia regularne; sys — kod wyjścia; time — przerwy między zapytaniami.
import json
import re
import sys
import time
# urllib.request — pobieranie stron; datetime — daty; Path — ścieżki.
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Katalog z danymi (data/ obok scripts/).
DATA = Path(__file__).resolve().parent.parent / "data"
# Ile ostatnich losowań trafia do pliku „recent” (Mini Lotto losuje codziennie — 100 to ponad 3 miesiące).
RECENT_COUNT = 100

# Gry: adres w archiwum, pule (ile liczb, największa liczba) i przesunięcie numeracji archiwum względem oficjalnej.
GAMES = {
    "lotto": {"slug": "lotto", "pools": [(6, 49)]},
    "mini-lotto": {"slug": "mini-lotto", "pools": [(5, 42)]},
    # Archiwum numeruje Eurojackpot od wejścia Polski (15.09.2017 = nr 1); oficjalny numer jest o 286 większy.
    "eurojackpot": {"slug": "eurojackpot", "pools": [(5, 50), (2, 12)], "number_offset": 286},
}

# Jedno losowanie w HTML archiwum: numer, data, liczby głównej puli, (opcjonalnie) liczby euro w <strong>.
DRAW = re.compile(
    r'class="nr_in_list"\s*>\s*(\d+)\.\s*</li>\s*'
    r'<li class="date_in_list">\s*(\d{2}-\d{2}-\d{4})\s*</li>'
    r'((?:\s*<li class="numbers_in_list[^"]*"\s*>\s*\d+\s*</li>)+)'
    r'((?:\s*<li class="tsn_number_in_list[^"]*">\s*<strong>\s*\d+\s*</strong>\s*</li>)*)'
)
# Pojedyncza liczba wewnątrz elementu listy.
NUMBER = re.compile(r">\s*(\d+)\s*<")


def read_csv(path: Path) -> list[tuple[int, datetime, list[int]]]:
    """Wiersze pliku: (numer, data, wszystkie liczby po kolei — pule jedna za drugą)."""
    rows = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        rows.append((int(parts[0]), datetime.strptime(parts[1], "%d.%m.%Y"), [int(n) for n in parts[2:]]))
    return rows


def format_row(nr: int, day: datetime, numbers: list[int]) -> str:
    """Wiersz CSV: numer 4-cyfrowy, data DD.MM.RRRR, liczby 2-cyfrowe."""
    return f"{nr:04d},{day:%d.%m.%Y}," + ",".join(f"{n:02d}" for n in numbers)


def fetch_year(slug: str, year: int) -> str:
    """HTML archiwum gry z danego roku."""
    request = urllib.request.Request(
        f"https://megalotto.pl/wyniki/{slug}/losowania-z-roku-{year}", headers={"User-Agent": "Mozilla/5.0"}
    )
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "ignore")
    # Sekunda przerwy — grzecznie wobec serwera.
    time.sleep(1)
    return html


def fetch_draws(game: dict, years: range) -> dict[int, tuple[datetime, list[int]]]:
    """Losowania z archiwum z podanych lat: numer (oficjalny) → (data, liczby wszystkich pul)."""
    draws = {}
    for year in years:
        for nr, day, main_nums, extra_nums in DRAW.findall(fetch_year(game["slug"], year)):
            numbers = sorted(int(n) for n in NUMBER.findall(main_nums))
            if len(game["pools"]) > 1:
                numbers += sorted(int(n) for n in NUMBER.findall(extra_nums))
            draws[int(nr) + game.get("number_offset", 0)] = (datetime.strptime(day, "%d-%m-%Y"), numbers)
    return draws


def valid_numbers(game: dict, numbers: list[int]) -> bool:
    """Czy liczby pasują do pul gry (ilość, zakres, bez powtórzeń w puli)."""
    offset = 0
    for pick, max_n in game["pools"]:
        pool = numbers[offset : offset + pick]
        if len(pool) != pick or len(set(pool)) != pick or min(pool) < 1 or max(pool) > max_n:
            return False
        offset += pick
    return offset == len(numbers)


def update_game(game_id: str, game: dict) -> dict:
    """Dopisuje nowe losowania gry. Zwraca wpis do manifestu."""
    path = DATA / f"{game_id}.csv"
    rows = read_csv(path)
    last_nr, last_day, _ = rows[-1]
    # Lata od roku ostatniego losowania w pliku do dziś (na przełomie roku — oba).
    years = range(last_day.year, datetime.now().year + 1)
    fetched = fetch_draws(game, years)

    # Kontrola zgodności: losowania, które już mamy, powinny się zgadzać z archiwum (tylko ostrzeżenie).
    known = {nr: (day, numbers) for nr, day, numbers in rows if day.year >= last_day.year}
    for nr, (day, numbers) in fetched.items():
        if nr in known and known[nr] != (day, numbers):
            print(f"UWAGA {game_id}: losowanie {nr} różni się od archiwum", file=sys.stderr)

    # Nowe losowania: numery większe niż ostatni, kolejno bez luk.
    added = []
    nr = last_nr + 1
    previous_day = last_day
    while nr in fetched:
        day, numbers = fetched[nr]
        if day < previous_day or not valid_numbers(game, numbers):
            sys.exit(f"{game_id}: niepoprawne losowanie {nr} {day:%d.%m.%Y} {numbers} — przerywam")
        added.append((nr, day, numbers))
        previous_day = day
        nr += 1
    # Numery większe niż ciąg bez luk — archiwum ma lukę; nie zgadujemy, czekamy na uzupełnienie.
    if any(n > nr for n in fetched):
        print(f"UWAGA {game_id}: w archiwum brakuje losowania {nr}, dalsze pominięte", file=sys.stderr)

    if added:
        with path.open("a", encoding="utf-8") as file:
            for row in added:
                file.write(format_row(*row) + "\n")
        rows += added
        print(f"{game_id}: dopisano {len(added)} (ostatnie: {added[-1][0]}, {added[-1][1]:%d.%m.%Y})")
    else:
        print(f"{game_id}: bez zmian (ostatnie: {last_nr})")

    # Plik z ostatnimi losowaniami — zawsze odtwarzany z pełnej historii.
    recent = rows[-RECENT_COUNT:]
    (DATA / f"{game_id}-recent.csv").write_text("\n".join(format_row(*r) for r in recent) + "\n", "utf-8")
    last = rows[-1]
    return {
        "lastDrawNo": last[0],
        "lastDate": f"{last[1]:%Y-%m-%d}",
        "count": len(rows),
        "recentFrom": recent[0][0],
    }


def main() -> None:
    manifest_path = DATA / "manifest.json"
    old = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    games = {game_id: update_game(game_id, game) for game_id, game in GAMES.items()}
    # Znacznik czasu zmieniamy tylko przy zmianie danych — inaczej akcja robiłaby commit co dzień bez potrzeby.
    changed = games != old.get("games")
    manifest = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if changed else old.get("updatedAt"),
        "games": games,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")


if __name__ == "__main__":
    main()
