import os
import json
import tempfile
import shutil
from flask import Blueprint, request, jsonify
from database.db import get_db
from processing.csv_parser import parse_zip, parse_csv_folder
from processing.analyzer import (
    segment_all_channels, lap_stats, compute_distance_ft, build_track_map
)
from api.sessions import _recompute_session_stats
import config

upload_bp = Blueprint('upload', __name__)


def _ingest_channels(db, session_id, recording_name, channels, source_type, driver=None):
    """
    Save a parsed channel dict into the database.
    Returns the new recording_id.
    """
    laps_df = channels.get('laps')
    if laps_df is None or len(laps_df) == 0:
        raise ValueError("No lap timing data found in recording")

    lap_count = len(laps_df)
    duration_s = float(laps_df['start'].max() + laps_df['time'].max()) if len(laps_df) > 0 else 0.0

    cur = db.execute(
        "INSERT INTO recordings (session_id, name, source_type, lap_count, duration_s, driver) VALUES (?,?,?,?,?,?)",
        (session_id, recording_name, source_type, lap_count, duration_s, driver)
    )
    recording_id = cur.lastrowid

    # Store telemetry as JSON
    for ch_name, ch_df in channels.items():
        if ch_name == 'laps':
            data = ch_df.to_dict(orient='records')
        elif ch_name == 'gps':
            keep = ['time', 'lat', 'lon', 'speed_mph', 'alt_ft', 'accuracy']
            keep = [c for c in keep if c in ch_df.columns]
            data = ch_df[keep].round(6).to_dict(orient='records')
        else:
            data = ch_df[['time', 'value']].round(6).to_dict(orient='records')
        db.execute(
            "INSERT OR REPLACE INTO telemetry (recording_id, channel, data_json) VALUES (?,?,?)",
            (recording_id, ch_name, json.dumps(data))
        )

    # Segment channels into laps and compute per-lap stats
    lap_segs = segment_all_channels(channels, laps_df)
    for _, row in laps_df.iterrows():
        lap_num = int(row['lap'])
        t_start = float(row['start'])
        lap_time = float(row['time'])
        segs = lap_segs.get(lap_num, {})
        stats = lap_stats(
            lap_num,
            segs.get('gps'),
            segs.get('inline_acc'),
            segs.get('lateral_acc'),
        )
        # Compute GPS distance for completeness validation
        gps_seg = segs.get('gps')
        gps_dist_ft = None
        if gps_seg is not None and len(gps_seg) > 1:
            try:
                g_dist = compute_distance_ft(gps_seg)
                gps_dist_ft = round(float(g_dist['distance_ft'].max()), 1)
            except Exception:
                pass
        db.execute(
            """INSERT INTO laps
               (recording_id, session_id, lap_number, start_time, lap_time,
                max_speed, avg_speed, max_lat_g, max_inline_g, gps_distance_ft)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (recording_id, session_id, lap_num, t_start, lap_time,
             stats.get('max_speed'), stats.get('avg_speed'),
             stats.get('max_lat_g'), stats.get('max_inline_g'), gps_dist_ft)
        )

    # Invalidate analysis cache for this session
    db.execute("DELETE FROM analysis_cache WHERE session_id = ?", (session_id,))

    return recording_id


@upload_bp.route('/sessions/<int:session_id>/upload', methods=['POST'])
def upload_recording(session_id):
    db = get_db()
    sess = db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not sess:
        db.close()
        return jsonify({'error': 'Session not found'}), 404

    if 'file' not in request.files:
        db.close()
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    filename = f.filename.lower()
    driver = (request.form.get('driver') or '').strip() or None
    # Validate driver name
    VALID_DRIVERS = {'Jayden', 'Kolten', 'James'}
    if driver and driver not in VALID_DRIVERS:
        driver = None

    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    tmp_path = os.path.join(config.UPLOAD_DIR, f.filename)
    f.save(tmp_path)

    try:
        if filename.endswith('.zip'):
            recording_name, channels = parse_zip(tmp_path)
            source_type = 'csv_zip'
        elif filename.endswith('.xrk'):
            from processing.xrk_parser import parse_xrk
            recording_name, channels = parse_xrk(tmp_path)
            source_type = 'xrk'
        else:
            return jsonify({'error': 'Unsupported file type. Upload a .zip or .xrk file'}), 400

        recording_id = _ingest_channels(db, session_id, recording_name, channels, source_type, driver=driver)
        _recompute_session_stats(db, session_id)
        db.commit()

        sess_row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        db.close()
        return jsonify({
            'recording_id': recording_id,
            'recording_name': recording_name,
            'driver': driver,
            'session': dict(sess_row),
        }), 201

    except Exception as e:
        db.close()
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
