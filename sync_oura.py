import os
import requests
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv
import logging

load_dotenv()
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
OURA_TOKEN = os.environ["OURA_PERSONAL_TOKEN"]
HEADERS = {"Authorization": f"Bearer {OURA_TOKEN}"}
BASE = "https://api.ouraring.com/v2/usercollection"


def fetch_sleep(start_date: str, end_date: str) -> dict:
    resp = requests.get(
        f"{BASE}/daily_sleep",
        headers=HEADERS,
        params={"start_date": start_date, "end_date": end_date}
    )
    log.info(f"Sleep API status: {resp.status_code}")
    resp.raise_for_status()
    return {d["day"]: d for d in resp.json().get("data", [])}


def fetch_readiness(start_date: str, end_date: str) -> dict:
    resp = requests.get(
        f"{BASE}/daily_readiness",
        headers=HEADERS,
        params={"start_date": start_date, "end_date": end_date}
    )
    log.info(f"Readiness API status: {resp.status_code}")
    resp.raise_for_status()
    return {d["day"]: d for d in resp.json().get("data", [])}


def upsert_scores(sleep_by_day: dict, readiness_by_day: dict):
    rows = []
    all_days = set(sleep_by_day) | set(readiness_by_day)
    for day in all_days:
        s = sleep_by_day.get(day, {})
        r = readiness_by_day.get(day, {})
        rows.append({
            "date":                  day,
            "score":                 s.get("score"),
            "readiness_score":       r.get("score"),
            "hrv_avg":               s.get("average_hrv"),
            "rhr":                   s.get("lowest_heart_rate"),
            "total_sleep_minutes":   round(s.get("total_sleep_duration", 0) / 60) if s.get("total_sleep_duration") else None,
            "deep_sleep_minutes":    round(s.get("deep_sleep_duration", 0) / 60) if s.get("deep_sleep_duration") else None,
            "rem_sleep_minutes":     round(s.get("rem_sleep_duration", 0) / 60) if s.get("rem_sleep_duration") else None,
            "efficiency":            s.get("efficiency"),
            "temperature_deviation": r.get("temperature_deviation"),
            "raw_data":              {"sleep": s, "readiness": r},
        })

    if rows:
        supabase.table("sleep_scores").upsert(rows).execute()
        log.info(f"Upserted {len(rows)} Oura days")


def main():
    end = datetime.utcnow().date()
    start = end - timedelta(days=30)
    log.info(f"Fetching Oura data from {start} to {end}")
    sleep = fetch_sleep(str(start), str(end))
    readiness = fetch_readiness(str(start), str(end))
    upsert_scores(sleep, readiness)
    log.info("Oura sync complete")


if __name__ == "__main__":
    main()

