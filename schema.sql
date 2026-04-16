-- ═══════════════════════════════════════════════════════
-- Marathon Coach — Supabase Schema
-- Run this in your Supabase SQL editor to set up all tables
-- ═══════════════════════════════════════════════════════

-- Activities (Strava + Garmin)
CREATE TABLE IF NOT EXISTS activities (
    id              TEXT PRIMARY KEY,          -- Strava/Garmin activity ID
    source          TEXT NOT NULL,             -- 'strava' | 'garmin'
    sport_type      TEXT,                      -- 'Run' | 'Ride' | 'VirtualRun'
    name            TEXT,
    start_date      TIMESTAMPTZ NOT NULL,
    distance_km     NUMERIC(6,2),
    duration_seconds INT,
    elevation_gain_m NUMERIC(6,1),
    average_heartrate NUMERIC(5,1),
    max_heartrate   NUMERIC(5,1),
    average_pace_min_km NUMERIC(5,2),         -- mins per km
    suffer_score    INT,                       -- Strava training load proxy
    average_power_w INT,                       -- Garmin/cycling
    vo2max_estimate NUMERIC(4,1),              -- Garmin
    cadence_avg     INT,
    raw_data        JSONB,                     -- full API response
    synced_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_date DESC);
CREATE INDEX IF NOT EXISTS idx_activities_sport ON activities(sport_type);

-- Sleep & Recovery (Oura)
CREATE TABLE IF NOT EXISTS sleep_scores (
    date                DATE PRIMARY KEY,
    score               INT,                   -- Oura sleep score 0-100
    readiness_score     INT,                   -- Oura readiness score 0-100
    hrv_avg             NUMERIC(6,1),          -- avg HRV ms (RMSSD)
    rhr                 INT,                   -- resting heart rate
    total_sleep_minutes INT,
    deep_sleep_minutes  INT,
    rem_sleep_minutes   INT,
    efficiency          NUMERIC(4,1),          -- sleep efficiency %
    temperature_deviation NUMERIC(4,2),        -- °C from baseline
    raw_data            JSONB,
    synced_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep_scores(date DESC);

-- Planned Workouts (Final Surge)
CREATE TABLE IF NOT EXISTS planned_workouts (
    id              TEXT PRIMARY KEY,
    planned_date    DATE NOT NULL,
    workout_type    TEXT,                      -- 'Easy Run' | 'Tempo' | 'Long Run' | 'Intervals' | 'Rest'
    description     TEXT,
    planned_distance_km NUMERIC(5,1),
    planned_duration_min INT,
    target_pace_min_km  NUMERIC(4,2),
    target_hr_zone  INT,                       -- 1-5
    notes           TEXT,
    completed       BOOLEAN DEFAULT FALSE,
    actual_activity_id TEXT REFERENCES activities(id),
    synced_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_planned_date ON planned_workouts(planned_date);

-- Weekly training load rollup (materialised view for fast queries)
CREATE MATERIALIZED VIEW IF NOT EXISTS weekly_load AS
SELECT
    date_trunc('week', start_date) AS week_start,
    COUNT(*)                        AS activity_count,
    ROUND(SUM(distance_km)::numeric, 1) AS total_km,
    ROUND(SUM(duration_seconds) / 60.0) AS total_minutes,
    SUM(suffer_score)               AS training_load,
    COUNT(*) FILTER (WHERE sport_type = 'Run') AS run_count,
    ROUND(AVG(average_heartrate))   AS avg_hr
FROM activities
GROUP BY 1
ORDER BY 1 DESC;

-- Refresh the view (call this after syncing new data)
-- REFRESH MATERIALIZED VIEW weekly_load;
