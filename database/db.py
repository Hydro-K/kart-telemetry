import sqlite3
import os
from database.models import SCHEMA
import config

def get_db():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)

    # Seed karts if not present
    row = conn.execute("SELECT COUNT(*) FROM karts").fetchone()[0]
    if row == 0:
        conn.execute("INSERT INTO karts (name, color) VALUES (?, ?)", ("Kart #6", "#00d4aa"))
        conn.execute("INSERT INTO karts (name, color) VALUES (?, ?)", ("Kart #70", "#ff6b35"))
        conn.commit()
    else:
        # Migrate old generic names to real kart numbers
        conn.execute("UPDATE karts SET name='Kart #6'  WHERE id=1 AND name='Kart 1'")
        conn.execute("UPDATE karts SET name='Kart #70' WHERE id=2 AND name='Kart 2'")
        conn.commit()

    # Schema migrations: add columns that may not exist in older DBs
    _add_column_if_missing(conn, 'recordings', 'driver', 'TEXT')
    _add_column_if_missing(conn, 'laps', 'gps_distance_ft', 'REAL')
    conn.commit()
    conn.close()


def _add_column_if_missing(conn, table, column, col_type):
    """Add a column to an existing table if it doesn't already exist."""
    existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
