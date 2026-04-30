from flask import Blueprint, jsonify
from database.db import get_db

karts_bp = Blueprint('karts', __name__)


@karts_bp.route('/karts', methods=['GET'])
def list_karts():
    db = get_db()
    karts = db.execute("SELECT * FROM karts ORDER BY id").fetchall()
    result = []
    for k in karts:
        kart = dict(k)
        stats = db.execute(
            """SELECT COUNT(*) as session_count,
                      MIN(best_lap_time) as all_time_best,
                      AVG(avg_lap_time) as overall_avg,
                      MAX(max_speed_mph) as top_speed,
                      SUM(lap_count) as total_laps
               FROM sessions WHERE kart_id = ?""",
            (k['id'],)
        ).fetchone()
        kart.update(dict(stats))
        result.append(kart)
    db.close()
    return jsonify(result)


@karts_bp.route('/karts/<int:kart_id>/sessions', methods=['GET'])
def kart_sessions(kart_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM sessions WHERE kart_id = ? ORDER BY created_at DESC",
        (kart_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@karts_bp.route('/karts/compare', methods=['GET'])
def compare_karts():
    db = get_db()
    karts = db.execute("SELECT * FROM karts ORDER BY id").fetchall()
    result = {}
    for k in karts:
        kart_id = k['id']
        stats = db.execute(
            """SELECT MIN(best_lap_time) as best_lap,
                      AVG(avg_lap_time) as avg_lap,
                      MAX(max_speed_mph) as max_speed,
                      SUM(lap_count) as total_laps,
                      COUNT(*) as session_count
               FROM sessions WHERE kart_id = ? AND lap_count > 0""",
            (kart_id,)
        ).fetchone()
        # Get best lap stats in detail
        best_sess = db.execute(
            """SELECT id FROM sessions WHERE kart_id = ? AND best_lap_time IS NOT NULL
               ORDER BY best_lap_time ASC LIMIT 1""",
            (kart_id,)
        ).fetchone()
        best_lap_detail = None
        if best_sess:
            bl = db.execute(
                """SELECT l.lap_time, l.max_speed, l.max_lat_g, l.max_inline_g,
                          s.name as session_name
                   FROM laps l JOIN sessions s ON s.id = l.session_id
                   WHERE l.session_id = ? AND l.is_best = 1 LIMIT 1""",
                (best_sess['id'],)
            ).fetchone()
            if bl:
                best_lap_detail = dict(bl)
        # Lap time history (all laps, most recent sessions first)
        all_laps = db.execute(
            """SELECT l.global_lap, l.lap_time, l.is_best, s.name as session_name
               FROM laps l JOIN sessions s ON s.id = l.session_id
               WHERE l.session_id IN (SELECT id FROM sessions WHERE kart_id = ?)
               ORDER BY s.created_at ASC, l.global_lap ASC""",
            (kart_id,)
        ).fetchall()
        result[f'kart_{kart_id}'] = {
            'id': kart_id,
            'name': k['name'],
            'color': k['color'],
            'stats': dict(stats),
            'best_lap_detail': best_lap_detail,
            'lap_history': [dict(l) for l in all_laps],
        }
    db.close()
    return jsonify(result)
