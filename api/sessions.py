from flask import Blueprint, request, jsonify
from database.db import get_db

sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('/sessions', methods=['GET'])
def list_sessions():
    kart_id = request.args.get('kart_id', type=int)
    db = get_db()
    if kart_id:
        rows = db.execute(
            """SELECT s.*, k.name as kart_name, k.color as kart_color
               FROM sessions s JOIN karts k ON k.id = s.kart_id
               WHERE s.kart_id = ? ORDER BY s.created_at DESC""",
            (kart_id,)
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT s.*, k.name as kart_name, k.color as kart_color
               FROM sessions s JOIN karts k ON k.id = s.kart_id
               ORDER BY s.created_at DESC"""
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Attach distinct drivers for this session
        drv_rows = db.execute(
            "SELECT DISTINCT driver FROM recordings WHERE session_id=? AND driver IS NOT NULL",
            (d['id'],)
        ).fetchall()
        d['drivers'] = [dr['driver'] for dr in drv_rows]
        result.append(d)
    db.close()
    return jsonify(result)


@sessions_bp.route('/sessions', methods=['POST'])
def create_session():
    data = request.get_json()
    name = data.get('name', '').strip()
    kart_id = data.get('kart_id')
    event_date = data.get('event_date')
    notes = data.get('notes', '')
    if not name or not kart_id:
        return jsonify({'error': 'name and kart_id required'}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO sessions (kart_id, name, event_date, notes) VALUES (?,?,?,?)",
        (kart_id, name, event_date, notes)
    )
    db.commit()
    session_id = cur.lastrowid
    row = db.execute(
        """SELECT s.*, k.name as kart_name, k.color as kart_color
           FROM sessions s JOIN karts k ON k.id = s.kart_id WHERE s.id = ?""",
        (session_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(row)), 201


@sessions_bp.route('/sessions/<int:session_id>', methods=['GET'])
def get_session(session_id):
    db = get_db()
    row = db.execute(
        """SELECT s.*, k.name as kart_name, k.color as kart_color
           FROM sessions s JOIN karts k ON k.id = s.kart_id WHERE s.id = ?""",
        (session_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    recordings = db.execute(
        "SELECT * FROM recordings WHERE session_id = ? ORDER BY uploaded_at ASC",
        (session_id,)
    ).fetchall()
    laps = db.execute(
        "SELECT * FROM laps WHERE session_id = ? ORDER BY global_lap ASC",
        (session_id,)
    ).fetchall()
    drv_rows = db.execute(
        "SELECT DISTINCT driver FROM recordings WHERE session_id=? AND driver IS NOT NULL",
        (session_id,)
    ).fetchall()
    db.close()
    result = dict(row)
    result['recordings'] = [dict(r) for r in recordings]
    result['laps'] = [dict(l) for l in laps]
    result['drivers'] = [dr['driver'] for dr in drv_rows]
    return jsonify(result)


@sessions_bp.route('/sessions/<int:session_id>', methods=['PATCH'])
def update_session(session_id):
    data = request.get_json()
    db = get_db()
    row = db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    if 'name' in data:
        db.execute("UPDATE sessions SET name = ? WHERE id = ?", (data['name'], session_id))
    if 'kart_id' in data:
        db.execute("UPDATE sessions SET kart_id = ? WHERE id = ?", (data['kart_id'], session_id))
    if 'notes' in data:
        db.execute("UPDATE sessions SET notes = ? WHERE id = ?", (data['notes'], session_id))
    if 'event_date' in data:
        db.execute("UPDATE sessions SET event_date = ? WHERE id = ?", (data['event_date'], session_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@sessions_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    db = get_db()
    db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@sessions_bp.route('/recordings/<int:recording_id>', methods=['DELETE'])
def delete_recording(recording_id):
    db = get_db()
    rec = db.execute("SELECT session_id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if not rec:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    session_id = rec['session_id']
    db.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
    db.commit()
    _recompute_session_stats(db, session_id)
    db.commit()
    db.close()
    return jsonify({'ok': True})


def _recompute_session_stats(db, session_id):
    """Recalculate and update aggregated stats on the sessions row."""
    import config
    import numpy as np
    from processing.analyzer import compute_consistency
    laps = db.execute(
        "SELECT lap_time, max_speed, gps_distance_ft FROM laps WHERE session_id = ?", (session_id,)
    ).fetchall()
    # Filter out install/warmup laps shorter than the minimum time threshold
    time_filtered = [l for l in laps if l['lap_time'] and l['lap_time'] >= config.MIN_LAP_TIME_S]

    # GPS completeness filter: exclude laps covering less than 85% of the circuit.
    # Use the 75th-percentile GPS distance as the reference circuit length —
    # this is robust because partial outlaps are always much shorter than full laps.
    all_dists = [l['gps_distance_ft'] for l in time_filtered if l['gps_distance_ft'] and l['gps_distance_ft'] > 0]
    if len(all_dists) >= 4:
        sorted_dists = sorted(all_dists)
        p75_dist = sorted_dists[int(len(sorted_dists) * 0.75)]
        min_dist = p75_dist * 0.85  # require at least 85% of the typical circuit distance
        valid_laps = [l for l in time_filtered
                      if l['gps_distance_ft'] is None or l['gps_distance_ft'] >= min_dist]
    else:
        valid_laps = time_filtered

    times = [l['lap_time'] for l in valid_laps]
    speeds = [l['max_speed'] for l in valid_laps if l['max_speed']]
    if not times:
        db.execute(
            """UPDATE sessions SET lap_count=0, best_lap_time=NULL, avg_lap_time=NULL,
               consistency_pct=NULL, max_speed_mph=NULL WHERE id=?""",
            (session_id,)
        )
        return
    arr = np.array(times)
    # Use 2-sigma outlier filter for best/avg to exclude lingering slow laps
    mean, std = arr.mean(), arr.std()
    if std > 0:
        filtered = arr[np.abs(arr - mean) <= config.OUTLIER_LAP_STD_MULT * std]
    else:
        filtered = arr
    racing_times = filtered.tolist() if len(filtered) >= 1 else times
    best = min(racing_times)
    avg = sum(racing_times) / len(racing_times)
    consistency = compute_consistency(times)
    max_spd = max(speeds) if speeds else None
    db.execute(
        """UPDATE sessions SET lap_count=?, best_lap_time=?, avg_lap_time=?,
           consistency_pct=?, max_speed_mph=? WHERE id=?""",
        (len(times), round(best, 3), round(avg, 3), consistency,
         round(max_spd, 2) if max_spd else None, session_id)
    )
    # Mark best lap (only among valid racing laps)
    db.execute("UPDATE laps SET is_best=0 WHERE session_id=?", (session_id,))
    db.execute(
        """UPDATE laps SET is_best=1 WHERE session_id=? AND lap_time=?
           AND rowid = (SELECT rowid FROM laps WHERE session_id=? AND lap_time=? LIMIT 1)""",
        (session_id, best, session_id, best)
    )
    # Assign global_lap numbers
    all_laps = db.execute(
        """SELECT id FROM laps WHERE session_id=?
           ORDER BY recording_id ASC, lap_number ASC""",
        (session_id,)
    ).fetchall()
    for i, row in enumerate(all_laps, start=1):
        db.execute("UPDATE laps SET global_lap=? WHERE id=?", (i, row['id']))
