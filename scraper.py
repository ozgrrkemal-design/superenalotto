import json
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

DRAWS_FILE = Path(__file__).parent / "draws.json"
URL = "https://www.superenalotto.net/estrazioni"

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def parse_italian_date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip().lower())
    if not m:
        return None
    day, month_name, year = m.groups()
    month = ITALIAN_MONTHS.get(month_name)
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def load_existing() -> dict:
    if not DRAWS_FILE.exists():
        return {}
    raw = DRAWS_FILE.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = json.loads(raw.decode("utf-8"))
    return {d["date"]: d for d in data}


def save(existing: dict) -> None:
    all_draws = sorted(existing.values(), key=lambda d: d["date"], reverse=True)
    with open(DRAWS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_draws, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_draws)} total draws.")


def scrape_with_playwright(existing: dict) -> list[dict]:
    new_draws = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        )
        print(f"Fetching {URL} ...")
        page.goto(URL, wait_until="networkidle", timeout=30000)

        # Try to find draw rows — try multiple selector patterns
        rows = page.query_selector_all("tr, li.estrazione, div.estrazione, .draw-row, .result-row")
        print(f"Found {len(rows)} candidate rows")

        for row in rows:
            text = row.inner_text()
            # Look for a draw number pattern like "70/26"
            id_match = re.search(r"\b(\d+/\d+)\b", text)
            if not id_match:
                continue
            draw_id = id_match.group(1)

            # Look for a date
            date_str = parse_italian_date(text)
            if not date_str:
                continue

            # Already have this draw
            if date_str in existing:
                continue

            # Extract numbers 1-90 from the row
            nums = [int(n) for n in re.findall(r"\b([1-9]|[1-8][0-9]|90)\b", text)]
            # Remove the year digits (e.g. 26 from "70/26") and day numbers
            # We expect at least 8 numbers: 6 main + jolly + superstar
            if len(nums) < 8:
                continue

            # Heuristic: first 6 unique numbers sorted = main, 7th = jolly, 8th = superstar
            # But need to deduplicate artifacts from date/id
            unique_nums = []
            seen = set()
            for n in nums:
                if n not in seen and 1 <= n <= 90:
                    seen.add(n)
                    unique_nums.append(n)
            if len(unique_nums) < 8:
                continue

            main = sorted(unique_nums[:6])
            jolly = unique_nums[6]
            superstar = unique_nums[7]

            draw = {
                "id": draw_id,
                "date": date_str,
                "numbers": main,
                "jolly": jolly,
                "superstar": superstar,
            }
            new_draws.append(draw)
            existing[date_str] = draw
            print(f"  New draw: {draw_id} {date_str} {main} J:{jolly} SS:{superstar}")

        # Fallback: try parsing the full page text if no rows found
        if not new_draws:
            print("Row selector failed, trying full-page text parse...")
            content = page.inner_text("body")
            new_draws = parse_page_text(content, existing)

        browser.close()
    return new_draws


def parse_page_text(text: str, existing: dict) -> list[dict]:
    """Fallback: find draw blocks in raw page text."""
    new_draws = []
    # Split on draw id pattern
    blocks = re.split(r"(?=\b\d{1,3}/\d{2}\b)", text)
    for block in blocks:
        id_match = re.match(r"(\d{1,3}/\d{2})", block.strip())
        if not id_match:
            continue
        draw_id = id_match.group(1)
        date_str = parse_italian_date(block)
        if not date_str or date_str in existing:
            continue
        nums = [int(n) for n in re.findall(r"\b([1-9]|[1-8][0-9]|90)\b", block)]
        unique = list(dict.fromkeys(n for n in nums if 1 <= n <= 90))
        if len(unique) < 8:
            continue
        main = sorted(unique[:6])
        jolly = unique[6]
        superstar = unique[7]
        draw = {"id": draw_id, "date": date_str, "numbers": main, "jolly": jolly, "superstar": superstar}
        new_draws.append(draw)
        existing[date_str] = draw
        print(f"  (fallback) {draw_id} {date_str} {main} J:{jolly} SS:{superstar}")
    return new_draws


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] SuperEnalotto scraper starting...")
    existing = load_existing()
    print(f"Existing draws: {len(existing)}")
    new_draws = scrape_with_playwright(existing)
    print(f"New draws found: {len(new_draws)}")
    save(existing)


if __name__ == "__main__":
    main()
