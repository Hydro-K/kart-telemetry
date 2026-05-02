"""
Analysis endpoints — all return data in mph / feet.
Results are cached in analysis_cache after first computation.
"""

import json
import numpy as np
import pandas as pd
from flask import Blueprint, request, jsonify
from database.db import get_db
from processing.analyzer import (
    segment_all_channels, segment_channel, lap_stats,
    compute_distance_ft, build_track_map, detect_zones,
    zone_percentages, speed_histogram, lap_delta, format_lap_time
)

analysis_bp = Blueprint('analysis', __name__)


def _load_channels(db, recording_id):
    """Load all telemetry channels for a recording from DB into DataFrames."""
    rows = db.execute(
        "SELECT channel, data_json FROM telemetry WHERE recording_id = ?",
        (recording_id,)
    ).fetchall()
    channels = {}
    for row in rows:
        data = json.loads(row['data_json'])
        if not data:
            continue
        df = pd.DataFrame(data)
        channels[row['channel']] = df
    return channels


def _get_cached(db, session_id, key):
    row = db.execute(
        "SELECT result_json FROM analysis_cache WHERE session_id=? AND analysis_key=?",
        (session_id, key)
    ).fetchone()
    return json.loads(row['result_json']) if row else None


def _set_cache(db, session_id, key, data):
    db.execute(
        "INSERT OR REPLACE INTO analysis_cache (session_id, analysis_key, result_json) VALUES (?,?,?)",
        (session_id, key, json.dumps(data))
    )
    db.commit()


def _get_recording_for_lap(db, session_id, global_lap):
    """Return (recording_id, local_lap_number) for a global lap number in a session."""
    row = db.execute(
        "SELECT recording_id, lap_number FROM laps WHERE session_id=? AND global_lap=?",
        (session_id, global_lap)
    ).fetchone()
    if not row:
        return None, None
    return row['recording_id'], row['lap_number']


def _load_lap_segment(db, session_id, global_lap, channel):
    """Load a single channel segment for a specific global lap."""
    recording_id, local_lap = _get_recording_for_lap(db, session_id, global_lap)
    if recording_id is None:
        return None, None
    channels = _load_channels(db, recording_id)
    laps_df = channels.get('laps')
    if laps_df is None:
        return None, None
    ch_df = channels.get(channel)
    if ch_df is None:
        return None, None
    lap_row = laps_df[laps_df['lap'] == local_lap]
    if len(lap_row) == 0:
        return None, None
    t_start = float(lap_row.iloc[0]['start'])
    t_end = t_start + float(lap_row.iloc[0]['time'])
    seg = segment_channel(ch_df, t_start, t_end)
    return seg, t_start


def _get_all_laps_data(db, session_id, clean_only=False):
    """Return laps for a session as list of dicts.
    If clean_only=True, applies the same time+GPS filters as _recompute_session_stats
    so the overview only shows laps that count toward session statistics.
    """
    rows = db.execute(
        """SELECT l.*, r.name as recording_name
           FROM laps l JOIN recordings r ON r.id = l.recording_id
           WHERE l.session_id = ? ORDER BY l.global_lap ASC""",
        (session_id,)
    ).fetchall()
    laps = [dict(r) for r in rows]

    if not clean_only:
        return laps

    import config
    # Step 1: time filter
    time_filtered = [l for l in laps if l['lap_time'] and l['lap_time'] >= config.MIN_LAP_TIME_S]

    # Step 2: GPS distance completeness filter
    all_dists = [l['gps_distance_ft'] for l in time_filtered
                 if l.get('gps_distance_ft') and l['gps_distance_ft'] > 0]
    if len(all_dists) >= 4:
        sorted_dists = sorted(all_dists)
        p75 = sorted_dists[int(len(sorted_dists) * 0.75)]
        min_dist = p75 * 0.85
        return [l for l in time_filtered
                if not l.get('gps_distance_ft') or l['gps_distance_ft'] >= min_dist]
    return time_filtered


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/overview', methods=['GET'])
def overview(session_id):
    db = get_db()
    cached = _get_cached(db, session_id, 'overview')
    if cached:
        db.close()
        return jsonify(cached)
    sess = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not sess:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    laps = _get_all_laps_data(db, session_id, clean_only=True)
    result = {
        'session_id': session_id,
        'name': sess['name'],
        'lap_count': sess['lap_count'] or 0,
        'best_lap_time': sess['best_lap_time'],
        'best_lap_formatted': format_lap_time(sess['best_lap_time']) if sess['best_lap_time'] else '--',
        'avg_lap_time': sess['avg_lap_time'],
        'avg_lap_formatted': format_lap_time(sess['avg_lap_time']) if sess['avg_lap_time'] else '--',
        'consistency_pct': sess['consistency_pct'],
        'max_speed_mph': sess['max_speed_mph'],
        'laps': [
            {
                'global_lap': l['global_lap'],
                'lap_number': l['lap_number'],
                'recording_name': l['recording_name'],
                'lap_time': l['lap_time'],
                'lap_time_formatted': format_lap_time(l['lap_time']),
                'is_best': bool(l['is_best']),
                'max_speed': l['max_speed'],
                'max_lat_g': l['max_lat_g'],
                'max_inline_g': l['max_inline_g'],
            }
            for l in laps
        ],
    }
    _set_cache(db, session_id, 'overview', result)
    db.close()
    return jsonify(result)


# ---------------------------------------------------------------------------
# Lap times
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/lap_times', methods=['GET'])
def lap_times(session_id):
    db = get_db()
    laps = _get_all_laps_data(db, session_id, clean_only=True)
    db.close()
    return jsonify([
        {
            'global_lap': l['global_lap'],
            'recording_name': l['recording_name'],
            'lap_time': l['lap_time'],
            'lap_time_formatted': format_lap_time(l['lap_time']),
            'is_best': bool(l['is_best']),
        }
        for l in laps
    ])


# ---------------------------------------------------------------------------
# Lap progression
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/lap_progression', methods=['GET'])
def lap_progression(session_id):
    db = get_db()
    laps = _get_all_laps_data(db, session_id, clean_only=True)
    db.close()
    return jsonify({
        'global_laps': [l['global_lap'] for l in laps],
        'lap_times': [l['lap_time'] for l in laps],
        'is_best': [bool(l['is_best']) for l in laps],
        'recording_names': [l['recording_name'] for l in laps],
    })


# ---------------------------------------------------------------------------
# Speed trace
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/speed_trace', methods=['GET'])
def speed_trace(session_id):
    lap = request.args.get('lap', type=int)
    db = get_db()
    if lap is None:
        sess = db.execute(
            "SELECT best_lap_time FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        best_row = db.execute(
            "SELECT global_lap FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
            (session_id,)
        ).fetchone()
        lap = best_row['global_lap'] if best_row else 1

    seg, _ = _load_lap_segment(db, session_id, lap, 'gps')
    db.close()
    if seg is None or len(seg) == 0:
        return jsonify({'time': [], 'distance_ft': [], 'speed_mph': []})
    seg = compute_distance_ft(seg)
    return jsonify({
        'time': [round(float(v), 3) for v in seg['lap_time'].values],
        'distance_ft': [round(float(v), 1) for v in seg['distance_ft'].values],
        'speed_mph': [round(float(v), 2) for v in seg['speed_mph'].values],
    })


# ---------------------------------------------------------------------------
# Track map
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/track_map', methods=['GET'])
def track_map(session_id):
    lap = request.args.get('lap', type=int)
    db = get_db()
    if lap is None:
        best_row = db.execute(
            "SELECT global_lap FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
            (session_id,)
        ).fetchone()
        lap = best_row['global_lap'] if best_row else 1

    seg, _ = _load_lap_segment(db, session_id, lap, 'gps')
    db.close()
    if seg is None:
        return jsonify({'x_ft': [], 'y_ft': [], 'speed_mph': []})
    result = build_track_map(seg)
    return jsonify(result or {'x_ft': [], 'y_ft': [], 'speed_mph': []})


# ---------------------------------------------------------------------------
# Full track map (all laps combined — for overview track shape)
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/full_track_map', methods=['GET'])
def full_track_map(session_id):
    cached_key = 'full_track_map'
    db = get_db()
    cached = _get_cached(db, session_id, cached_key)
    if cached:
        db.close()
        return jsonify(cached)
    recordings = db.execute(
        "SELECT id FROM recordings WHERE session_id=?", (session_id,)
    ).fetchall()
    all_lat, all_lon, all_spd = [], [], []
    for rec in recordings:
        channels = _load_channels(db, rec['id'])
        gps = channels.get('gps')
        if gps is not None and len(gps) > 0:
            all_lat.extend(gps['lat'].tolist())
            all_lon.extend(gps['lon'].tolist())
            all_spd.extend(gps['speed_mph'].tolist())
    db.close()
    if not all_lat:
        return jsonify({'x_ft': [], 'y_ft': [], 'speed_mph': []})
    import numpy as np
    from processing.analyzer import latlon_to_xy_ft, _downsample
    lat = np.array(all_lat)
    lon = np.array(all_lon)
    spd = np.array(all_spd)
    x, y = latlon_to_xy_ft(lat, lon)
    max_pts = 2000
    if len(x) > max_pts:
        idx = np.round(np.linspace(0, len(x)-1, max_pts)).astype(int)
        x, y, spd = x[idx], y[idx], spd[idx]
    result = {
        'x_ft': [round(float(v), 1) for v in x],
        'y_ft': [round(float(v), 1) for v in y],
        'speed_mph': [round(float(v), 2) for v in spd],
    }
    return jsonify(result)


# ---------------------------------------------------------------------------
# G-G diagram
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/gg_diagram', methods=['GET'])
def gg_diagram(session_id):
    lap_param = request.args.get('lap', 'all')
    db = get_db()
    laps = _get_all_laps_data(db, session_id)

    lateral_g, inline_g, speed_mph = [], [], []

    if lap_param == 'all':
        target_laps = [l['global_lap'] for l in laps]
    else:
        target_laps = [int(lap_param)]

    for gl in target_laps:
        lat_seg, _ = _load_lap_segment(db, session_id, gl, 'lateral_acc')
        inl_seg, _ = _load_lap_segment(db, session_id, gl, 'inline_acc')
        gps_seg, _ = _load_lap_segment(db, session_id, gl, 'gps')
        if lat_seg is None or inl_seg is None:
            continue
        import numpy as np
        t_inl = inl_seg['lap_time'].values
        lg_vals = np.interp(t_inl, lat_seg['lap_time'].values, lat_seg['value'].values)
        ig_vals = inl_seg['value'].values
        if gps_seg is not None and len(gps_seg) > 0:
            spd_vals = np.interp(t_inl, gps_seg['lap_time'].values, gps_seg['speed_mph'].values)
        else:
            spd_vals = np.zeros(len(t_inl))
        # Downsample to max 500 pts per lap
        step = max(1, len(t_inl) // 500)
        lateral_g.extend([round(float(v), 3) for v in lg_vals[::step]])
        inline_g.extend([round(float(v), 3) for v in ig_vals[::step]])
        speed_mph.extend([round(float(v), 2) for v in spd_vals[::step]])

    db.close()
    return jsonify({'lateral_g': lateral_g, 'inline_g': inline_g, 'speed_mph': speed_mph})


# ---------------------------------------------------------------------------
# Acceleration traces
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/acceleration_traces', methods=['GET'])
def acceleration_traces(session_id):
    lap = request.args.get('lap', type=int)
    db = get_db()
    if lap is None:
        best_row = db.execute(
            "SELECT global_lap FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
            (session_id,)
        ).fetchone()
        lap = best_row['global_lap'] if best_row else 1

    inl, _ = _load_lap_segment(db, session_id, lap, 'inline_acc')
    lat, _ = _load_lap_segment(db, session_id, lap, 'lateral_acc')
    vert, _ = _load_lap_segment(db, session_id, lap, 'vertical_acc')
    db.close()

    def _series(seg):
        if seg is None or len(seg) == 0:
            return [], []
        return ([round(float(v), 3) for v in seg['lap_time'].values],
                [round(float(v), 4) for v in seg['value'].values])

    inl_t, inl_v = _series(inl)
    lat_t, lat_v = _series(lat)
    vert_t, vert_v = _series(vert)
    return jsonify({
        'time': inl_t,
        'inline_g': inl_v,
        'lateral_g': lat_v,
        'vertical_g': vert_v,
    })


# ---------------------------------------------------------------------------
# Rotation traces
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/rotation_traces', methods=['GET'])
def rotation_traces(session_id):
    lap = request.args.get('lap', type=int)
    db = get_db()
    if lap is None:
        best_row = db.execute(
            "SELECT global_lap FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
            (session_id,)
        ).fetchone()
        lap = best_row['global_lap'] if best_row else 1

    yaw, _ = _load_lap_segment(db, session_id, lap, 'yaw_rate')
    pitch, _ = _load_lap_segment(db, session_id, lap, 'pitch_rate')
    roll, _ = _load_lap_segment(db, session_id, lap, 'roll_rate')
    db.close()

    def _series(seg):
        if seg is None or len(seg) == 0:
            return [], []
        return ([round(float(v), 3) for v in seg['lap_time'].values],
                [round(float(v), 3) for v in seg['value'].values])

    yaw_t, yaw_v = _series(yaw)
    _, pitch_v = _series(pitch)
    _, roll_v = _series(roll)
    return jsonify({
        'time': yaw_t,
        'yaw_rate': yaw_v,
        'pitch_rate': pitch_v,
        'roll_rate': roll_v,
    })


# ---------------------------------------------------------------------------
# Best lap breakdown (zones)
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/best_lap_breakdown', methods=['GET'])
def best_lap_breakdown(session_id):
    db = get_db()
    lap = request.args.get('lap', type=int)
    if lap is None:
        best_row = db.execute(
            "SELECT global_lap, lap_time FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
            (session_id,)
        ).fetchone()
        lap = best_row['global_lap'] if best_row else 1
        lap_time_val = best_row['lap_time'] if best_row else None
    else:
        lr = db.execute("SELECT lap_time FROM laps WHERE session_id=? AND global_lap=?",
                        (session_id, lap)).fetchone()
        lap_time_val = lr['lap_time'] if lr else None

    gps_seg, _ = _load_lap_segment(db, session_id, lap, 'gps')
    inl_seg, _ = _load_lap_segment(db, session_id, lap, 'inline_acc')
    lat_seg, _ = _load_lap_segment(db, session_id, lap, 'lateral_acc')
    db.close()

    zones = detect_zones(inl_seg, lat_seg)
    gps_seg = compute_distance_ft(gps_seg) if gps_seg is not None else None
    return jsonify({
        'lap_num': lap,
        'lap_time': round(float(lap_time_val), 3) if lap_time_val else None,
        'time': [round(float(v), 3) for v in (gps_seg['lap_time'].values if gps_seg is not None else [])],
        'speed_mph': [round(float(v), 2) for v in (gps_seg['speed_mph'].values if gps_seg is not None else [])],
        'distance_ft': [round(float(v), 1) for v in (gps_seg['distance_ft'].values if gps_seg is not None else [])],
        'zones': zones,
    })


# ---------------------------------------------------------------------------
# Zone pie
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/zone_pie', methods=['GET'])
def zone_pie(session_id):
    db = get_db()
    best_row = db.execute(
        "SELECT global_lap FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
        (session_id,)
    ).fetchone()
    lap = best_row['global_lap'] if best_row else 1
    inl_seg, _ = _load_lap_segment(db, session_id, lap, 'inline_acc')
    lat_seg, _ = _load_lap_segment(db, session_id, lap, 'lateral_acc')
    db.close()
    return jsonify(zone_percentages(inl_seg, lat_seg))


# ---------------------------------------------------------------------------
# Speed histogram
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/speed_histogram', methods=['GET'])
def speed_hist(session_id):
    db = get_db()
    recordings = db.execute(
        "SELECT id FROM recordings WHERE session_id=?", (session_id,)
    ).fetchall()
    import numpy as np
    all_speeds = []
    for rec in recordings:
        channels = _load_channels(db, rec['id'])
        gps = channels.get('gps')
        if gps is not None and 'speed_mph' in gps.columns:
            all_speeds.extend(gps['speed_mph'].tolist())
    db.close()
    if not all_speeds:
        return jsonify({'bins': [], 'counts': []})
    import pandas as pd
    dummy_df = pd.DataFrame({'speed_mph': all_speeds})
    return jsonify(speed_histogram(dummy_df, bins=25))


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/battery', methods=['GET'])
def battery(session_id):
    db = get_db()
    recordings = db.execute(
        "SELECT id FROM recordings WHERE session_id=? ORDER BY uploaded_at ASC",
        (session_id,)
    ).fetchall()
    times, voltages = [], []
    offset = 0.0
    for rec in recordings:
        channels = _load_channels(db, rec['id'])
        bat = channels.get('battery')
        if bat is not None and len(bat) > 0:
            t = bat['time'].values
            v = bat['value'].values
            times.extend([round(float(x) + offset, 3) for x in t])
            voltages.extend([round(float(x), 3) for x in v])
            offset += float(t[-1])
    db.close()
    return jsonify({'time': times, 'voltage': voltages})


# ---------------------------------------------------------------------------
# Lap comparison
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/lap_compare', methods=['GET'])
def lap_compare(session_id):
    lap1 = request.args.get('lap1', type=int)
    lap2 = request.args.get('lap2', type=int)
    if not lap1 or not lap2:
        return jsonify({'error': 'lap1 and lap2 params required'}), 400
    db = get_db()
    gps1, _ = _load_lap_segment(db, session_id, lap1, 'gps')
    gps2, _ = _load_lap_segment(db, session_id, lap2, 'gps')
    inl1, _ = _load_lap_segment(db, session_id, lap1, 'inline_acc')
    inl2, _ = _load_lap_segment(db, session_id, lap2, 'inline_acc')
    db.close()

    if gps1 is None or gps2 is None:
        return jsonify({'error': 'Lap data not found'}), 404

    dist, delta, spd1, spd2 = lap_delta(gps1, gps2)

    def _inl_series(seg, dist_arr, gps_seg):
        if seg is None or gps_seg is None or len(dist_arr) == 0:
            return [0.0] * len(dist_arr)
        import numpy as np
        gps_with_d = compute_distance_ft(gps_seg)
        t_at_dist = np.interp(dist_arr, gps_with_d['distance_ft'].values, gps_with_d['lap_time'].values)
        vals = np.interp(t_at_dist, seg['lap_time'].values, seg['value'].values)
        return [round(float(v), 3) for v in vals]

    return jsonify({
        'distance_ft': dist,
        'lap1_speed_mph': spd1,
        'lap2_speed_mph': spd2,
        'lap1_inline_g': _inl_series(inl1, dist, gps1),
        'lap2_inline_g': _inl_series(inl2, dist, gps2),
        'delta_time': delta,
    })


# ---------------------------------------------------------------------------
# Theoretical Best Lap
# Splits the circuit into mini-sectors by distance and finds the fastest time
# each sector was achieved across all clean laps. Sum = "perfect lap" time.
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/theoretical_best', methods=['GET'])
def theoretical_best(session_id):
    N_SECTORS = 50
    db = get_db()
    laps = _get_all_laps_data(db, session_id, clean_only=True)
    if not laps:
        db.close()
        return jsonify({'error': 'No clean laps found'}), 404

    best_lap_row = db.execute(
        "SELECT global_lap, lap_time FROM laps WHERE session_id=? AND is_best=1 LIMIT 1",
        (session_id,)
    ).fetchone()
    actual_best = best_lap_row['lap_time'] if best_lap_row else None

    sector_best_time  = [float('inf')] * N_SECTORS
    sector_best_lap   = [None] * N_SECTORS
    circuit_dist      = None
    lap_sector_times  = {}   # global_lap → list of sector times

    for lap in laps:
        gl = lap['global_lap']
        gps_seg, _ = _load_lap_segment(db, session_id, gl, 'gps')
        if gps_seg is None or len(gps_seg) < 10:
            continue
        gps_seg = compute_distance_ft(gps_seg)
        lap_dist = float(gps_seg['distance_ft'].max())
        if lap_dist < 100:
            continue
        if circuit_dist is None:
            circuit_dist = lap_dist

        sector_size = circuit_dist / N_SECTORS
        lap_times_for_sectors = []
        for i in range(N_SECTORS):
            s_start = i * sector_size
            s_end   = (i + 1) * sector_size
            mask = (gps_seg['distance_ft'] >= s_start) & (gps_seg['distance_ft'] < s_end)
            sector_pts = gps_seg[mask]
            if len(sector_pts) < 2:
                lap_times_for_sectors.append(None)
                continue
            sector_time = float(sector_pts['lap_time'].max() - sector_pts['lap_time'].min())
            lap_times_for_sectors.append(round(sector_time, 4))
            if sector_time < sector_best_time[i]:
                sector_best_time[i] = sector_time
                sector_best_lap[i]  = gl
        lap_sector_times[gl] = lap_times_for_sectors

    db.close()

    # Only count sectors where we have real data
    valid_sectors = [(t, sl) for t, sl in zip(sector_best_time, sector_best_lap)
                     if t != float('inf')]
    if not valid_sectors:
        return jsonify({'error': 'Not enough GPS data to compute theoretical best'}), 400

    theo_best = round(sum(t for t, _ in valid_sectors), 3)
    gap = round(actual_best - theo_best, 3) if actual_best else None

    # Which laps contributed sectors
    from collections import Counter
    contributing_laps = Counter(sl for _, sl in valid_sectors if sl is not None)
    top_contributors = [
        {'global_lap': gl, 'sectors_contributed': cnt}
        for gl, cnt in contributing_laps.most_common(5)
    ]

    # Build sector-by-sector breakdown for chart
    sector_chart = []
    for i, (best_t, best_lap_gl) in enumerate(zip(sector_best_time, sector_best_lap)):
        if best_t == float('inf'):
            continue
        sector_chart.append({
            'sector': i + 1,
            'best_time': round(best_t, 4),
            'best_lap': best_lap_gl,
        })

    return jsonify({
        'theoretical_best':  theo_best,
        'theoretical_best_formatted': format_lap_time(theo_best),
        'actual_best':       round(actual_best, 3) if actual_best else None,
        'actual_best_formatted': format_lap_time(actual_best) if actual_best else '--',
        'time_left_on_table': gap,
        'time_left_formatted': f'+{gap:.3f}s' if gap else '--',
        'sectors_analysed':  len(valid_sectors),
        'top_contributing_laps': top_contributors,
        'sector_chart': sector_chart,
    })


# ---------------------------------------------------------------------------
# Race Simulation (Monte Carlo)
# Simulates N race laps for each driver using historical lap time distribution.
# Returns finish position probabilities for Jayden's kart vs. competitors.
# ---------------------------------------------------------------------------

@analysis_bp.route('/analysis/<int:session_id>/race_sim', methods=['GET'])
def race_sim(session_id):
    race_laps   = request.args.get('laps',       type=int, default=20)
    n_opponents = request.args.get('opponents',  type=int, default=3)
    n_trials    = request.args.get('trials',     type=int, default=2000)
    opp_delta   = request.args.get('opp_delta',  type=float, default=0.0)
    # opp_delta: seconds offset for opponent mean pace vs our mean (positive = slower opponent)

    # Clamp inputs to sensible limits
    race_laps   = max(1,  min(race_laps,   100))
    n_opponents = max(1,  min(n_opponents, 9))
    n_trials    = max(100, min(n_trials,   5000))

    db = get_db()
    laps = _get_all_laps_data(db, session_id, clean_only=True)
    db.close()
    if len(laps) < 3:
        return jsonify({'error': 'Need at least 3 clean laps to run a simulation'}), 400

    lap_times = np.array([l['lap_time'] for l in laps])
    mean_t = float(lap_times.mean())
    std_t  = float(lap_times.std())
    best_t = float(lap_times.min())

    # Opponent pace: same std, but shifted mean by opp_delta
    opp_mean = mean_t + opp_delta
    opp_std  = std_t  * 1.1   # slightly more variable

    position_counts = np.zeros(n_opponents + 1, dtype=int)  # index 0 = position 1

    rng = np.random.default_rng(42)
    for _ in range(n_trials):
        # Simulate our total race time
        our_times  = rng.normal(mean_t, std_t,  race_laps)
        our_times  = np.clip(our_times, best_t, mean_t * 2.5)
        our_total  = float(our_times.sum())

        # Simulate each opponent
        opp_totals = []
        for _ in range(n_opponents):
            opp_t = rng.normal(opp_mean, opp_std, race_laps)
            opp_t = np.clip(opp_t, best_t * 0.95, opp_mean * 2.5)
            opp_totals.append(float(opp_t.sum()))

        # Rank: count how many opponents beat us
        position = 1 + sum(1 for ot in opp_totals if ot < our_total)
        position_counts[position - 1] += 1

    finish_probs = [
        {
            'position': i + 1,
            'probability': round(int(position_counts[i]) / n_trials * 100, 1),
            'count': int(position_counts[i]),
        }
        for i in range(n_opponents + 1)
    ]

    # Expected position
    exp_pos = sum((i + 1) * position_counts[i] for i in range(n_opponents + 1)) / n_trials

    # Best/worst/p50 total race time
    our_all = rng.normal(mean_t, std_t, (n_trials, race_laps))
    our_all = np.clip(our_all, best_t, mean_t * 2.5)
    totals  = our_all.sum(axis=1)

    return jsonify({
        'race_laps':        race_laps,
        'n_opponents':      n_opponents,
        'n_trials':         n_trials,
        'our_mean_lap':     round(mean_t, 3),
        'our_mean_formatted': format_lap_time(mean_t),
        'our_best_lap':     round(best_t, 3),
        'our_best_formatted': format_lap_time(best_t),
        'our_std':          round(std_t, 3),
        'opponent_mean_lap': round(opp_mean, 3),
        'opp_delta':        opp_delta,
        'expected_position': round(exp_pos, 1),
        'finish_probabilities': finish_probs,
        'projected_race_time': {
            'best_case':  format_lap_time(float(np.percentile(totals, 5))),
            'median':     format_lap_time(float(np.percentile(totals, 50))),
            'worst_case': format_lap_time(float(np.percentile(totals, 95))),
        },
    })
