import os
import time
import requests
import re
import logging
import csv
from datetime import date, timedelta, timezone, datetime
from dateutil import parser
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Reads API Key from GitHub Secrets
SERPER_API_KEY = os.getenv("SERPER_API_KEY") 

# SET TIME WINDOW (24 or 48 Hours)
SEARCH_WINDOW_HOURS = 48 

# DYNAMIC DATE: Always starts from "Today"
TARGET_DATE = date.today()

IST_OFFSET = timedelta(hours=5, minutes=30)
MAX_WORKERS = 5
API_TIMEOUT = 20

# Fixed filename to make it easy for the Emailer to find
OUTPUT_FILENAME = "daily_stock_news.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COMPANIES = [
    "Reliance Industries","RELIANCE","HDFC Bank","HDFCBANK","Tata Consultancy Services","TCS",
    "Infosys","INFY","ICICI Bank","ICICIBANK","Hindustan Unilever"
]

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def create_retry_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502], allowed_methods=["POST"])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"})
    return session

def parse_time(date_str):
    if not date_str: return ""
    if re.search(r'\d+\s+(minute|hour|day|week)s?\s+ago|just now', date_str, re.IGNORECASE):
        return date_str
    try:
        dt = parser.parse(date_str, fuzzy=True)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc + IST_OFFSET).strftime("%d %b %Y, %I:%M %p")
    except: return date_str

def fetch_company_news(session, rank, stock):
    time.sleep(0.5)
    # Calculate Past Date based on window
    start_date = TARGET_DATE - timedelta(hours=SEARCH_WINDOW_HOURS)
    
    # Search logic: News FROM start_date TO today
    payload = {
        "q": f'"{stock}" OR "{stock}.NS" after:{start_date} before:{TARGET_DATE}',
        "num": 10, "gl": "in", "hl": "en"
    }
    try:
        res = session.post("https://google.serper.dev/news", json=payload, timeout=API_TIMEOUT)
        return rank, stock, res.json().get("news", []) if res.status_code == 200 else None
    except: return rank, stock, None

# ==========================================
# 3. MAIN EXECUTION
# ==========================================
def main():
    if not SERPER_API_KEY:
        raise ValueError("API Key is missing! Check GitHub Secrets.")

    print(f"Fetching news for Last {SEARCH_WINDOW_HOURS} Hours until {TARGET_DATE}")
    all_results = []
    session = create_retry_session()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_company_news, session, i, stock): stock for i, stock in enumerate(COMPANIES, 1)}
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
