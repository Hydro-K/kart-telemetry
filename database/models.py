SCHEMA = """
CREATE TABLE IF NOT EXISTS karts (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL,
    color TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kart_id         INTEGER NOT NULL REFERENCES karts(id),
    name            TEXT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    event_date      DATE,
    notes           TEXT,
    lap_count       INTEGER DEFAULT 0,
    best_lap_time   REAL,
    avg_lap_time    REAL,
    consistency_pct REAL,
    max_speed_mph   REAL
);

CREATE TABLE IF NOT EXISTS recordings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    source_type  TEXT NOT NULL,
    lap_count    INTEGER,
    duration_s   REAL,
    driver       TEXT    -- e.g. 'Jayden', 'Kolten', 'James'
);

CREATE TABLE IF NOT EXISTS laps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    lap_number    INTEGER NOT NULL,
    global_lap    INTEGER,
    start_time    REAL NOT NULL,
    lap_time      REAL NOT NULL,
    is_best       BOOLEAN DEFAULT 0,
    max_speed     REAL,
    avg_speed     REAL,
    max_lat_g     REAL,
    max_inline_g  REAL,
    gps_distance_ft REAL   -- total GPS distance for lap completeness check
);

CREATE TABLE IF NOT EXISTS telemetry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    channel       TEXT NOT NULL,
    data_json     TEXT NOT NULL,
    UNIQUE(recording_id, channel)
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    analysis_key TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    computed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, analysis_key)
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    kart_id     INTEGER REFERENCES karts(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_laps_session ON laps(session_id);
CREATE INDEX IF NOT EXISTS idx_laps_recording ON laps(recording_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_recording ON telemetry(recording_id);
CREATE INDEX IF NOT EXISTS idx_recordings_session ON recordings(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_kart ON sessions(kart_id);
CREATE INDEX IF NOT EXISTS idx_ai_session ON ai_conversations(session_id);
"""
