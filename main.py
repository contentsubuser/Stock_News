import os
import time
import requests
import re
import logging
import csv
from datetime import timezone, timedelta
from dateutil import parser
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# 1. CONFIGURATION
# ==========================================
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Time frame (24 / 48 / 72) is chosen in the GitHub Actions "Run workflow" form
SEARCH_WINDOW_HOURS = int(os.getenv("SEARCH_WINDOW_HOURS", "24"))

# Stock list lives in this file - edit it to add/remove stocks
COMPANIES_FILE = "companies.txt"
OUTPUT_FILENAME = "daily_stock_news.csv"

IST_OFFSET = timedelta(hours=5, minutes=30)
MAX_WORKERS = 5
API_TIMEOUT = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def load_companies(path=COMPANIES_FILE):
    """Reads 'Company Name | TICKER' lines; blank lines and # comments are skipped."""
    companies = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, ticker = line.partition("|")
            companies.append((name.strip(), ticker.strip()))
    return companies


def create_retry_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502], allowed_methods=["POST"])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"})
    return session


def time_filter():
    """Google 'tbs' recency filter: qdr:dN = past N days (24h=1, 48h=2, 72h=3)."""
    return f"qdr:d{max(1, round(SEARCH_WINDOW_HOURS / 24))}"


def parse_time(date_str):
    if not date_str:
        return ""
    if re.search(r'\d+\s+(minute|hour|day|week)s?\s+ago|just now', date_str, re.IGNORECASE):
        return date_str
    try:
        dt = parser.parse(date_str, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(IST_OFFSET)).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return date_str


def fetch_company_news(session, rank, name, ticker):
    time.sleep(0.5)
    terms = [f'"{name}"'] + ([f'"{ticker}"'] if ticker else [])
    payload = {
        "q": " OR ".join(terms),
        "tbs": time_filter(),
        "num": 10, "gl": "in", "hl": "en",
    }
    try:
        res = session.post("https://google.serper.dev/news", json=payload, timeout=API_TIMEOUT)
        return rank, name, res.json().get("news", []) if res.status_code == 200 else None
    except Exception:
        return rank, name, None


# ==========================================
# 3. MAIN EXECUTION
# ==========================================
def main():
    if not SERPER_API_KEY:
        raise ValueError("API Key is missing! Check GitHub Secrets.")

    companies = load_companies()
    print(f"Fetching news for last {SEARCH_WINDOW_HOURS} hours for {len(companies)} stocks")
    all_results = []
    session = create_retry_session()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_company_news, session, i, n, t) for i, (n, t) in enumerate(companies, 1)]
        for future in as_completed(futures):
            rank, stock, news = future.result()
            if news:
                seen = set()
                for item in news:
                    if item.get("link") not in seen:
                        seen.add(item.get("link"))
                        all_results.append([rank, stock, item.get("title"), parse_time(item.get("date")), item.get("source"), item.get("link")])
            else:
                all_results.append([rank, stock, "No Data / Error", "", "", ""])

    all_results.sort(key=lambda x: x[0])

    with open(OUTPUT_FILENAME, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["RANK", "STOCK", "HEADLINE", "TIME", "SOURCE", "LINK"])
        writer.writerows(all_results)

    print(f"Saved to {OUTPUT_FILENAME}")


if __name__ == "__main__":
    main()
