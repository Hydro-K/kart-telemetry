"""
Bulk import AiM CSV recording folders into the telemetry database.

Usage:
  python bulk_import.py --session-name "April 26 Practice" --kart 1 --folder "path/to/csv_folders/"
  python bulk_import.py --list          # show existing sessions

Options:
  --session-name   Name for the session (creates new if it doesn't exist)
  --kart           Kart number: 1 (teal) or 2 (orange)
  --folder         Path to a directory containing AiM CSV recording folders
  --xrk            Path to a single XRK file to add to the session
  --session-id     Add to an existing session by ID (skips --session-name and --kart)
  --list           List all existing sessions and exit
"""

import argparse
import os
import sys

# Make sure we run from the app root
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

from database.db import init_db, get_db
from api.sessions import _recompute_session_stats


def fmt(s):
    if s is None:
        return '--:--'
    m = int(s // 60)
    sec = s - m * 60
    return f'{m}:{sec:06.3f}'


def list_sessions(db):
    rows = db.execute(
        '''SELECT s.*, k.name as kart_name FROM sessions s
           JOIN karts k ON k.id = s.kart_id ORDER BY s.created_at DESC'''
    ).fetchall()
    if not rows:
        print('No sessions in database.')
        return
    print(f'\n{"ID":>4}  {"Kart":<8}  {"Name":<35}  {"Laps":>5}  {"Best":>10}  {"Avg":>10}')
    print('-' * 80)
    for r in rows:
        print(f'{r["id"]:>4}  {r["kart_name"]:<8}  {r["name"]:<35}  '
              f'{(r["lap_count"] or 0):>5}  {fmt(r["best_lap_time"]):>10}  {fmt(r["avg_lap_time"]):>10}')
    print()


def import_csv_folder(db, session_id, folder_path, driver=None):
    """Import one AiM CSV recording folder."""
    from processing.csv_parser import parse_csv_folder
    from api.upload import _ingest_channels
    name = os.path.basename(folder_path.rstrip('/\\'))
    try:
        channels = parse_csv_folder(folder_path)
        laps = channels.get('laps')
        n = len(laps) if laps is not None else 0
        rec_id = _ingest_channels(db, session_id, name, channels, 'csv_folder', driver=driver)
        db.commit()
        drv_str = f', driver={driver}' if driver else ''
        print(f'  OK  {name}  ({n} laps, rec_id={rec_id}{drv_str})')
        return n
    except Exception as e:
        print(f'  ERR {name}: {e}')
        return 0


def import_xrk(db, session_id, xrk_path, driver=None):
    """Import one XRK file."""
    from processing.xrk_parser import parse_xrk
    from api.upload import _ingest_channels
    try:
        name, channels = parse_xrk(xrk_path)
        laps = channels.get('laps')
        n = len(laps) if laps is not None else 0
        rec_id = _ingest_channels(db, session_id, name, channels, 'xrk', driver=driver)
        db.commit()
        drv_str = f', driver={driver}' if driver else ''
        print(f'  OK  {name}  ({n} laps, rec_id={rec_id}{drv_str})')
        return n
    except Exception as e:
        print(f'  ERR {xrk_path}: {e}')
        return 0


def main():
    parser = argparse.ArgumentParser(description='Bulk import AiM recordings into the telemetry database.')
    parser.add_argument('--session-name', help='Name for the session')
    parser.add_argument('--kart', type=int, choices=[1, 2], help='Kart number (1 or 2)')
    parser.add_argument('--folder', help='Directory containing AiM CSV recording folders')
    parser.add_argument('--xrk', help='Path to a single .xrk file')
    parser.add_argument('--session-id', type=int, help='Add to an existing session by ID')
    parser.add_argument('--date', help='Event date (YYYY-MM-DD)')
    parser.add_argument('--driver', choices=['Jayden', 'Kolten', 'James'], help='Driver for this batch of recordings')
    parser.add_argument('--list', action='store_true', help='List all sessions and exit')
    args = parser.parse_args()

    init_db()
    db = get_db()

    if args.list:
        list_sessions(db)
        db.close()
        return

    if not args.folder and not args.xrk:
        parser.print_help()
        sys.exit(1)

    # Get or create session
    if args.session_id:
        sess = db.execute('SELECT * FROM sessions WHERE id=?', (args.session_id,)).fetchone()
        if not sess:
            print(f'ERROR: Session {args.session_id} not found.')
            sys.exit(1)
        session_id = args.session_id
        print(f'Adding to session {session_id}: "{sess["name"]}"')
    else:
        if not args.session_name:
            print('ERROR: --session-name is required when creating a new session.')
            sys.exit(1)
        if not args.kart:
            print('ERROR: --kart (1 or 2) is required when creating a new session.')
            sys.exit(1)
        cur = db.execute(
            'INSERT INTO sessions (kart_id, name, event_date) VALUES (?,?,?)',
            (args.kart, args.session_name, args.date)
        )
        db.commit()
        session_id = cur.lastrowid
        print(f'Created session {session_id}: "{args.session_name}" (Kart {args.kart})')

    total_laps = 0

    # Import CSV folders
    if args.folder:
        folder = os.path.abspath(args.folder)
        if not os.path.isdir(folder):
            print(f'ERROR: Not a directory: {folder}')
            sys.exit(1)

        # Check if folder itself is an AiM recording (contains InlineAcc.csv)
        if os.path.exists(os.path.join(folder, 'InlineAcc.csv')):
            print(f'Importing single recording folder: {folder}')
            total_laps += import_csv_folder(db, session_id, folder)
        else:
            # Treat as container of recording folders
            subfolders = sorted([
                f for f in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, f))
            ])
            print(f'Found {len(subfolders)} recording folder(s) in {folder}')
            for sf in subfolders:
                total_laps += import_csv_folder(db, session_id, os.path.join(folder, sf), driver=args.driver)

    # Import XRK
    if args.xrk:
        print(f'Importing XRK: {args.xrk}')
        total_laps += import_xrk(db, session_id, args.xrk, driver=args.driver)

    # Recompute session stats
    _recompute_session_stats(db, session_id)
    db.commit()

    sess = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    print()
    print('=' * 60)
    print(f'Session:     {sess["name"]}')
    print(f'Best lap:    {fmt(sess["best_lap_time"])}')
    print(f'Avg lap:     {fmt(sess["avg_lap_time"])}')
    print(f'Laps:        {sess["lap_count"]} (clean full laps)')
    print(f'Top speed:   {sess["max_speed_mph"]} mph')
    print(f'Consistency: {sess["consistency_pct"]}%')
    print(f'Dashboard:   http://localhost:5000/dashboard/{session_id}')
    print('=' * 60)
    db.close()


if __name__ == '__main__':
    main()
