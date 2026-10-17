"""
scripts/update.py — dopisuje nowe losowania do plików w data/ i odświeża pliki dla aplikacji Numora.

Uruchamiane codziennie przez akcję GitHub (.github/workflows/update.yml), ręcznie: python3 scripts/update.py
Pełna przebudowa historii jednej gry (np. nowej): python3 scripts/update.py --rebuild kaskada

Pliki (bez nagłówka, przecinki, zera wiodące — ten sam format co w aplikacji):
    data/<gra>.csv          pełna historia, np. 7414,06.10.2026,08,26,27,35,42,46
    data/<gra>-recent.csv   ostatnie RECENT_COUNT losowań (aplikacja pobiera zwykle tylko ten mały plik)
    data/manifest.json      ostatni numer i data dla każdej gry — aplikacja sprawdza go przy starcie
    data/prizes.json        wygrane z PRIZE_DRAWS ostatnich losowań każdej gry + kumulacje Lotto i Eurojackpot
                            (tylko bieżące dane — historii wygranych nie zbieramy)

Źródło nowych losowań: roczne archiwa megalotto.pl (nieoficjalne). Historii NIE przepisujemy — dopisujemy tylko
losowania o numerach większych niż ostatni w pliku, po sprawdzeniu ciągłości numeracji, dat i liczb.
"""

# argparse — argumenty; json — manifest; re — wyrażenia regularne; sys — kod wyjścia; time — przerwy.
import argparse
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
# Z ilu ostatnich losowań każdej gry trzymamy tabele wygranych (kupon na wczorajsze losowanie nadal ma wynik,
# a Kaskada losuje dwa razy dziennie). Starsze wypadają z pliku.
PRIZE_DRAWS = 5

# Gry: adres w archiwum, pule (ile liczb, największa liczba) i przesunięcie numeracji archiwum względem oficjalnej.
# first_year — od którego roku budować pełną historię (--rebuild).
GAMES = {
    # Lotto: plik właściciela projektu jest źródłem prawdy — przebudowa z archiwum jest zablokowana (różni się w 7 starych losowaniach).
    "lotto": {"slug": "lotto", "pools": [(6, 49)], "first_year": None},
    "lotto-plus": {"slug": "lotto-plus", "pools": [(6, 49)], "first_year": 2012},
    # Mini Lotto od 1992 r. (wcześniej inny format i luki w archiwum).
    "mini-lotto": {"slug": "mini-lotto", "pools": [(5, 42)], "first_year": 1992},
    # Archiwum numeruje Eurojackpot od wejścia Polski (15.09.2017 = nr 1); oficjalny numer jest o 286 większy.
    # Liczby euro: 2 z 10 do 21.03.2022, od 25.03.2022 2 z 12 — walidujemy względem obecnego maksimum (12).
    "eurojackpot": {"slug": "eurojackpot", "pools": [(5, 50), (2, 12)], "number_offset": 286, "first_year": 2017},
    "ekstra-pensja": {"slug": "ekstra-pensja", "pools": [(5, 35), (1, 4)], "first_year": 2014},
    "ekstra-premia": {"slug": "ekstra-premia", "pools": [(5, 35), (1, 4)], "first_year": 2019},
    # Kaskada: 12 z 24, dwa losowania dziennie (14:00 i 22:00). W archiwum brakuje losowania nr 627 (28.04.2013),
    # więc historia zaczyna się od nr 628 — bez luki w numeracji.
    "kaskada": {"slug": "kaskada", "pools": [(12, 24)], "first_year": 2013, "first_nr": 628},
}

# Archiwum: każde losowanie to osobna lista <ul>…</ul>. W niej: numer, data, liczby główne (<li class="numbers_in_list">),
# liczby dodatkowe (euro, „1 z 4”) w <strong> wewnątrz <li class="tsn_number_in_list">. W Kaskadzie po 6. liczbie jest
# element „nowej linii” z godziną losowania i kolejną liczbą w <span class="pierwsza_liczba_w_nowym_wierszu">.
BLOCK = re.compile(r"<ul[^>]*>(.*?)</ul>", re.S)
NR = re.compile(r'class="nr_in_list"\s*>\s*(\d+)\.')
DATE = re.compile(r'class="date_in_list">\s*(\d{2}-\d{2}-\d{4})')
# Liczba główna: element zawierający od razu liczbę (element z godziną zaczyna się od <span>, więc tu nie pasuje).
MAIN = re.compile(r'<li class="numbers_in_list[^"]*"\s*>\s*(\d+)\s*<')
FIRST_IN_LINE = re.compile(r'class="pierwsza_liczba_w_nowym_wierszu">\s*(\d+)')
EXTRA = re.compile(r'class="tsn_number_in_list[^"]*">\s*<strong>\s*(\d+)')
# Odnośnik do tabeli wygranych losowania.
PRIZE_LINK = re.compile(r'href="(https://megalotto\.pl/wyniki/[^"]*wygrane-z-dnia-[^"]+)"')
# Tabela wygranych (pierwsza na stronie; w Eurojackpot druga to inne zestawienie) i jej wiersze/komórki.
PRIZE_TABLE = re.compile(r'<table class="dl_wygrane_table.*?</table>', re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
# Nazwy stopni w Lotto / Lotto Plus / Mini Lotto.
WORD_HITS = {"szóstka": 6, "piątka": 5, "czwórka": 4, "trójka": 3, "dwójka": 2}
# Odnośniki do tabel wygranych z ostatnio pobranych stron archiwum: (gra, numer) → adres.
PRIZE_LINKS: dict[tuple[str, int], str] = {}


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
        for block in BLOCK.findall(fetch_year(game["slug"], year)):
            nr, day = NR.search(block), DATE.search(block)
            # Listy bez numeru i daty to inne elementy strony (np. menu).
            if not nr or not day:
                continue
            numbers = sorted(int(n) for n in MAIN.findall(block) + FIRST_IN_LINE.findall(block))
            if len(game["pools"]) > 1:
                numbers += sorted(int(n) for n in EXTRA.findall(block))
            # Słownik po numerze: losowanie z przełomu roku (na stronach dwóch lat) liczymy raz.
            number = int(nr.group(1)) + game.get("number_offset", 0)
            draws[number] = (datetime.strptime(day.group(1), "%d-%m-%Y"), numbers)
            # Zapamiętujemy odnośnik do tabeli wygranych (użyty dla ostatnich losowań).
            link = PRIZE_LINK.search(block)
            if link:
                PRIZE_LINKS[(game["slug"], number)] = link.group(1)
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


def rebuild_game(game_id: str, game: dict) -> None:
    """Pełna historia gry z archiwum, od first_year — dla nowych gier (nadpisuje data/<gra>.csv)."""
    if game["first_year"] is None:
        sys.exit(f"{game_id}: przebudowa zablokowana (plik jest źródłem prawdy)")
    fetched = fetch_draws(game, range(game["first_year"], datetime.now().year + 1))
    # Pomijamy losowania sprzed first_nr (np. przed luką w archiwum).
    ordered = sorted((nr, v) for nr, v in fetched.items() if nr >= game.get("first_nr", 0))
    # Te same zasady co przy dopisywaniu: numeracja bez luk, daty niemalejące, poprawne liczby.
    errors = []
    for i, (nr, (day, numbers)) in enumerate(ordered):
        if nr != ordered[0][0] + i:
            errors.append(f"luka w numeracji przed losowaniem {nr}")
        if i > 0 and day < ordered[i - 1][1][0]:
            errors.append(f"data losowania {nr} wcześniejsza niż poprzedniego")
        if not valid_numbers(game, numbers):
            errors.append(f"niepoprawne liczby w losowaniu {nr}: {numbers}")
    if errors:
        sys.exit(f"{game_id}: {len(errors)} błędów, np.:\n" + "\n".join(errors[:10]))
    (DATA / f"{game_id}.csv").write_text("\n".join(format_row(nr, d, n) for nr, (d, n) in ordered) + "\n", "utf-8")
    print(f"{game_id}: zapisano {len(ordered)} losowań ({ordered[0][1][0]:%d.%m.%Y} – {ordered[-1][1][0]:%d.%m.%Y})")


def tier_hits(label: str) -> list[int] | None:
    """Stopień wygranej → trafienia w każdej puli: „piątka” → [5], „III (5 + 0)” → [5, 0], „12” → [12]."""
    label = label.strip().lower()
    if label in WORD_HITS:
        return [WORD_HITS[label]]
    pair = re.search(r"(\d+)\s*\+\s*(\d+)", label)
    if pair:
        return [int(pair.group(1)), int(pair.group(2))]
    if label.isdigit():
        return [int(label)]
    return None


def parse_amount(text: str) -> tuple[float | None, str | None]:
    """Kwota z tabeli: „7 229.00” → (7229.0, None); „5 000 zł przez 20 lat” → (None, tekst)."""
    compact = text.replace("\xa0", " ").strip()
    if re.fullmatch(r"[\d ]+(\.\d+)?", compact):
        return float(compact.replace(" ", "")), None
    return None, compact or None


def fetch_prize_table(url: str) -> list[dict]:
    """Stopnie wygranych losowania: trafienia, liczba wygranych, kwota (albo opis, np. renta)."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "ignore")
    time.sleep(1)
    table = PRIZE_TABLE.search(html)
    if not table:
        return []
    tiers = []
    for row in ROW.findall(table.group(0)):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in CELL.findall(row)]
        if len(cells) < 3 or not cells[1].isdigit():
            continue
        hits = tier_hits(cells[0])
        if hits is None:
            continue
        amount, text = parse_amount(cells[2])
        winners = int(cells[1])
        # „0.00” przy braku zwycięzców to nie kwota nagrody, tylko brak wypłaty — zapisujemy jako brak danych.
        if amount == 0 and winners == 0:
            amount = None
        tiers.append({"hits": hits, "winners": winners, "amount": amount, "text": text})
    return tiers


def fetch_jackpots() -> dict[str, float]:
    """Kumulacje na najbliższe losowanie ze strony głównej archiwum (Lotto, Eurojackpot)."""
    request = urllib.request.Request("https://megalotto.pl/", headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "ignore")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    jackpots = {}
    for name, game_id in (("Lotto", "lotto"), ("Eurojackpot", "eurojackpot")):
        found = re.search(r"KUMULACJA " + name + r" ([\d ]+) zł", text)
        if found:
            jackpots[game_id] = float(found.group(1).replace(" ", ""))
    return jackpots


def update_prizes() -> None:
    """Plik data/prizes.json: tabele wygranych ostatnich losowań i kumulacje."""
    path = DATA / "prizes.json"
    old = json.loads(path.read_text("utf-8")) if path.exists() else {"games": {}}
    games = {}
    try:
        jackpots = fetch_jackpots()
    except Exception as error:  # strona główna nie odpowiada — zostawiamy poprzednie kumulacje
        print(f"UWAGA: kumulacje niedostępne ({error})", file=sys.stderr)
        jackpots = {g: v.get("jackpot") for g, v in old["games"].items() if v.get("jackpot")}
    for game_id, game in GAMES.items():
        csv = DATA / f"{game_id}.csv"
        if not csv.exists():
            continue
        # Ostatnie losowania gry i to, co już mamy w pliku (nie pobieramy ponownie gotowych tabel).
        last_rows = read_csv(csv)[-PRIZE_DRAWS:]
        known = {d["drawNo"]: d for d in old["games"].get(game_id, {}).get("draws", [])}
        draws = []
        for nr, day, _ in reversed(last_rows):
            tiers = known.get(nr, {}).get("tiers") or []
            link = PRIZE_LINKS.get((game["slug"], nr))
            if not tiers and link:
                try:
                    tiers = fetch_prize_table(link)
                except Exception as error:
                    print(f"UWAGA {game_id}: wygrane losowania {nr} niedostępne ({error})", file=sys.stderr)
            if tiers:
                draws.append({"drawNo": nr, "date": f"{day:%Y-%m-%d}", "tiers": tiers})
        games[game_id] = {"draws": draws, "jackpot": jackpots.get(game_id)}
    changed = games != old.get("games")
    prizes = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if changed else old.get("updatedAt"),
        "games": games,
    }
    # Zapis bez wcięć — plik pobiera telefon przy każdym sprawdzeniu, więc liczy się rozmiar.
    path.write_text(json.dumps(prizes, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print("wygrane: " + ", ".join(f"{g} {len(v['draws'])}" for g, v in games.items()) + f"; kumulacje: {jackpots}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", choices=sorted(GAMES), help="przebuduj pełną historię jednej gry z archiwum")
    args = parser.parse_args()
    if args.rebuild:
        rebuild_game(args.rebuild, GAMES[args.rebuild])
    manifest_path = DATA / "manifest.json"
    old = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    # Gry, dla których mamy już plik (nowe trzeba najpierw zbudować przez --rebuild).
    games = {game_id: update_game(game_id, game) for game_id, game in GAMES.items() if (DATA / f"{game_id}.csv").exists()}
    # Znacznik czasu zmieniamy tylko przy zmianie danych — inaczej akcja robiłaby commit co dzień bez potrzeby.
    changed = games != old.get("games")
    manifest = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if changed else old.get("updatedAt"),
        "games": games,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    # Wygrane i kumulacje — po aktualizacji losowań (korzysta z odnośników zebranych przy pobieraniu archiwum).
    update_prizes()


if __name__ == "__main__":
    main()
