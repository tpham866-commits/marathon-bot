"""
Garmin summarizedActivities.json → Supabase importer
Run once to backfill all historical Garmin data.

Usage:
  Upload this script + your JSON file to a service that can run Python,
  OR use the Supabase Edge Function approach described in README.

For Railway: add this as a one-off service or run via the existing bot service.
"""

import json
import os
import sys
from datetime import datetime, timezone
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

RUNNING_TYPES = {
    "running", "treadmill_running", "trail_running", "track_running",
    "ultra_running", "indoor_running", "virtual_run"
}

def ms_to_datetime(ts_ms):
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()

def ms_to_seconds(ms):
    if not ms:
        return None
    return int(ms / 1000)

def mps_to_min_per_km(mps):
    """Convert metres/sec to min/km."""
    if not mps or mps == 0:
        return None
    return round((1000 / mps) / 60, 2)

def import_activities(json_path: str):
    with open(json_path) as f:
        data = json.load(f)

    activities = data[0]["summarizedActivitiesExport"]
    print(f"Found {len(activities)} total Garmin activities")

    rows = []
    for a in activities:
        activity_type = a.get("activityType", "")
        sport_type = a.get("sportType", "")

        # Map Garmin type to our sport_type
        if activity_type in RUNNING_TYPES:
            mapped_type = "Run"
        elif "cycling" in activity_type or "ride" in activity_type or "biking" in activity_type:
            mapped_type = "Ride"
        elif "swimming" in activity_type or "swim" in activity_type:
            mapped_type = "Swim"
        elif activity_type == "strength_training":
            mapped_type = "Strength"
        else:
            mapped_type = activity_type.replace("_", " ").title()

        distance_m = a.get("distance", 0) or 0
        avg_speed = a.get("avgSpeed", 0) or 0
        duration_ms = a.get("duration", 0) or 0

        rows.append({
            "id":                   f"garmin_{a['activityId']}",
            "source":               "garmin",
            "sport_type":           mapped_type,
            "name":                 a.get("name"),
            "start_date":           ms_to_datetime(a.get("beginTimestamp")),
            "distance_km":          round(distance_m / 1000, 2) if distance_m else None,
            "duration_seconds":     ms_to_seconds(duration_ms),
            "elevation_gain_m":     a.get("elevationGain"),
            "average_heartrate":    a.get("avgHr"),
            "max_heartrate":        a.get("maxHr"),
            "average_pace_min_km":  mps_to_min_per_km(avg_speed),
            "suffer_score":         round(a.get("activityTrainingLoad", 0)) if a.get("activityTrainingLoad") else None,
            "average_power_w":      int(a["avgPower"]) if a.get("avgPower") else None,
            "vo2max_estimate":      a.get("vO2MaxValue"),
            "cadence_avg":          a.get("avgRunCadence") or a.get("avgBikeCadence"),
            "raw_data":             a,
        })

    # Upsert in batches of 100
    total = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i+100]
        supabase.table("activities").upsert(batch).execute()
        total += len(batch)
        print(f"Imported {total}/{len(rows)} activities...")

    print(f"\nDone! {total} Garmin activities imported into Supabase.")

    # Show summary
    runs = [r for r in rows if r["sport_type"] == "Run"]
    print(f"Runs: {len(runs)}")
    print(f"Date range: {rows[-1]['start_date'][:10]} → {rows[0]['start_date'][:10]}")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "tpham866_gmail_com_0_summarizedActivities.json"
    import_activities(path)
