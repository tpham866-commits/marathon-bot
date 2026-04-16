"""
Strava → Supabase sync
Fetches recent activities via the Strava API and upserts into the activities table.

Schedule: run every hour via cron or a hosting platform (Railway, Render, etc.)
  0 * * * * python src/sync_strava.py
"""

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


def refresh_strava_token() -> str:
    """Refresh the Strava access token using the stored refresh token."""
    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type":    "refresh_token",
    })
    resp.raise_for_status()
    data = resp.json()
    # Persist new refresh token
    os.environ["STRAVA_REFRESH_TOKEN"] = data["refresh_token"]
    return data["access_token"]


def fetch_activities(token: str, after_days: int = 730) -> list[dict]:
    after_ts = int((datetime.utcnow() - timedelta(days=after_days)).timestamp())
    activities = []
    page = 1
    while True:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"after": after_ts, "per_page": 50, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        page += 1
    return activities


def upsert_activities(activities: list[dict]):
    rows = []
    for a in activities:
        pace = None
        if a.get("distance") and a.get("moving_time"):
            pace = (a["moving_time"] / 60) / (a["distance"] / 1000)

        rows.append({
            "id":                 str(a["id"]),
            "source":             "strava",
            "sport_type":         a.get("sport_type") or a.get("type"),
            "name":               a.get("name"),
            "start_date":         a.get("start_date"),
            "distance_km":        round(a.get("distance", 0) / 1000, 2),
            "duration_seconds":   a.get("moving_time"),
            "elevation_gain_m":   a.get("total_elevation_gain"),
            "average_heartrate":  a.get("average_heartrate"),
            "max_heartrate":      a.get("max_heartrate"),
            "average_pace_min_km": round(pace, 2) if pace else None,
            "suffer_score":       a.get("suffer_score"),
            "cadence_avg":        a.get("average_cadence"),
            "raw_data":           a,
        })

    if rows:
        supabase.table("activities").upsert(rows).execute()
        log.info(f"Upserted {len(rows)} Strava activities")


def main():
    token = refresh_strava_token()
    activities = fetch_activities(token)
    upsert_activities(activities)
    log.info("Strava sync complete")


if __name__ == "__main__":
    main()
