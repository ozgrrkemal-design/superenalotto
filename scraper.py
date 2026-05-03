import json
import re
import time
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DRAWS_FILE = Path(__file__).parent / "draws.json"
BASE_URL = "https://www.superenalotto.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def load_existing() -> dict:
    if not DRAWS_FILE.exists():
        return {}
    with open(DRAWS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # index by date for fast lookup
    return {d["date"]: d for d in data}


def parse_italian_date(text: str) -> str | None:
    """'sabato 3 maggio 2026' → '2026-05-03'"""
    text = text.strip().lower()
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2), m.group(3)
    month = ITALIAN_MONTHS.get(month_name)
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def scrape_page(url: str) -> list[dict]:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    draws = []

    for row in soup.select(".estrazioni-list li, .draw-row, tr.draw, .extraction"):
        try:
            # draw id  (e.g. "70/26")
            id_el = row.select_one(".concorso, .draw-id, td.concorso")
            draw_id = id_el.get_text(strip=True) if id_el else None

            # date
            date_el = row.select_one(".data, .draw-date, td.data")
            date_str = None
            if date_el:
                date_str = parse_italian_date(date_el.get_text(strip=True))

            # main numbers
            num_els = row.select(".numeri li, .numbers li, .ball, td.numeri span")
            numbers = [int(el.get_text(strip=True)) for el in num_els if el.get_text(strip=True).isdigit()]

            # jolly
            jolly_el = row.select_one(".jolly, .jolly-number, td.jolly")
            jolly = int(jolly_el.get_text(strip=True)) if jolly_el and jolly_el.get_text(strip=True).isdigit() else None

            # superstar
            ss_el = row.select_one(".superstar, .superstar-number, td.superstar")
            superstar = int(ss_el.get_text(strip=True)) if ss_el and ss_el.get_text(strip=True).isdigit() else None

            if date_str and len(numbers) == 6 and jolly is not None:
                draws.append({
                    "id": draw_id or "",
                    "date": date_str,
                    "numbers": sorted(numbers),
                    "jolly": jolly,
                    "superstar": superstar or 0,
                })
        except Exception:
            continue

    # Fallback: regex over raw text if structured parse yielded nothing
    if not draws:
        draws = regex_fallback(resp.text)

    return draws


def regex_fallback(html: str) -> list[dict]:
    """Best-effort regex extraction when CSS selectors don't match."""
    draws = []
    # Look for JSON-LD or inline data objects
    json_blocks = re.findall(r'\{[^{}]*"concorso"[^{}]*\}', html)
    for block in json_blocks:
        try:
            obj = json.loads(block)
            date_str = obj.get("data") or obj.get("date")
            numbers = obj.get("numeri") or obj.get("numbers", [])
            jolly = obj.get("jolly")
            superstar = obj.get("superstar", 0)
            if date_str and len(numbers) == 6 and jolly:
                draws.append({
                    "id": obj.get("concorso", ""),
                    "date": date_str,
                    "numbers": sorted(numbers),
                    "jolly": jolly,
                    "superstar": superstar,
                })
        except Exception:
            continue
    return draws


def fetch_recent_draws(existing: dict) -> list[dict]:
    new_draws = []

    # Page 1 (most recent)
    for page in range(1, 6):
        url = f"{BASE_URL}/estrazioni" if page == 1 else f"{BASE_URL}/estrazioni?page={page}"
        print(f"  Fetching {url} ...")
        try:
            page_draws = scrape_page(url)
        except Exception as e:
            print(f"  Error: {e}")
            break

        if not page_draws:
            print("  No draws found on this page, stopping.")
            break

        added = 0
        for d in page_draws:
            if d["date"] not in existing:
                new_draws.append(d)
                existing[d["date"]] = d
                added += 1

        print(f"  Found {len(page_draws)} draws, {added} new.")

        # Stop paging if all draws on this page already exist
        if added == 0:
            break

        time.sleep(1)

    return new_draws


def save(existing: dict) -> None:
    all_draws = sorted(existing.values(), key=lambda d: d["date"], reverse=True)
    with open(DRAWS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_draws, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_draws)} total draws to {DRAWS_FILE}")


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] SuperEnalotto scraper starting...")
    existing = load_existing()
    print(f"Existing draws: {len(existing)}")

    new_draws = fetch_recent_draws(existing)
    print(f"New draws found: {len(new_draws)}")

    save(existing)


if __name__ == "__main__":
    main()
