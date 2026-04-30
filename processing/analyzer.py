"""
Core analysis algorithms for kart telemetry data.
All inputs/outputs use US customary units (mph, feet) except raw g-forces and deg/s.
"""

import json
import math
import numpy as np
import pandas as pd
import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_lap_time(seconds):
    """Format seconds as mm:ss.sss."""
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:06.3f}"


def _interp(target_times, source_times, source_values):
    """Interpolate source values onto target_times using linear interpolation."""
    return np.interp(target_times, source_times, source_values,
                     left=source_values[0], right=source_values[-1])


def _downsample(arr, max_pts):
    """Thin an array to at most max_pts evenly-spaced indices."""
    if len(arr) <= max_pts:
        return arr
    idx = np.round(np.linspace(0, len(arr) - 1, max_pts)).astype(int)
    return arr[idx]


# ---------------------------------------------------------------------------
# GPS / spatial
# ---------------------------------------------------------------------------

def latlon_to_xy_ft(lat_arr, lon_arr):
    """
    Project lat/lon arrays to local x/y in feet, centered at the centroid.
    Simple equirectangular projection — accurate enough for a <1-mile circuit.
    """
    R_FT = 364567.0  # feet per degree latitude (111,120 m × 3.28084)
    lat_c = lat_arr.mean()
    lon_c = lon_arr.mean()
    x = (lon_arr - lon_c) * R_FT * math.cos(math.radians(lat_c))
    y = (lat_arr - lat_c) * R_FT
    return x, y


def compute_distance_ft(gps_df):
    """
    Add a 'distance_ft' column via trapezoidal integration of speed_mph.
    Returns the DataFrame with the new column.
    """
    speed_fps = gps_df['speed_mph'].values * 5280.0 / 3600.0
    dt = np.diff(gps_df['time'].values, prepend=gps_df['time'].values[0])
    dt[0] = 0.0
    gps_df = gps_df.copy()
    gps_df['distance_ft'] = np.cumsum(speed_fps * dt)
    return gps_df


# ---------------------------------------------------------------------------
# Lap segmentation
# ---------------------------------------------------------------------------

def segment_channel(channel_df, t_start, t_end, time_col='time'):
    """
    Slice a channel DataFrame to [t_start, t_end), normalize time to lap-relative.
    """
    mask = (channel_df[time_col] >= t_start) & (channel_df[time_col] < t_end)
    seg = channel_df[mask].copy()
    seg['lap_time'] = seg[time_col] - t_start
    return seg


def segment_all_channels(channels, laps_df):
    """
    For each lap in laps_df, slice every channel into a lap-relative segment.
    Returns dict: {lap_number: {channel_name: DataFrame}}
    """
    lap_segments = {}
    for _, row in laps_df.iterrows():
        lap_num = int(row['lap'])
        t_start = float(row['start'])
        t_end = t_start + float(row['time'])
        segs = {}
        for ch_name, ch_df in channels.items():
            if ch_name == 'laps':
                continue
            try:
                seg = segment_channel(ch_df, t_start, t_end)
                if len(seg) > 0:
                    segs[ch_name] = seg
            except Exception:
                pass
        lap_segments[lap_num] = segs
    return lap_segments


# ---------------------------------------------------------------------------
# Per-lap statistics
# ---------------------------------------------------------------------------

def lap_stats(lap_num, gps_seg, inline_seg, lateral_seg):
    """Compute scalar stats for a single lap."""
    stats = {'lap_number': lap_num}
    if gps_seg is not None and len(gps_seg) > 0:
        stats['max_speed'] = round(float(gps_seg['speed_mph'].max()), 2)
        stats['avg_speed'] = round(float(gps_seg['speed_mph'].mean()), 2)
    else:
        stats['max_speed'] = None
        stats['avg_speed'] = None
    if lateral_seg is not None and len(lateral_seg) > 0:
        stats['max_lat_g'] = round(float(lateral_seg['value'].abs().max()), 3)
    else:
        stats['max_lat_g'] = None
    if inline_seg is not None and len(inline_seg) > 0:
        stats['max_inline_g'] = round(float(inline_seg['value'].abs().max()), 3)
    else:
        stats['max_inline_g'] = None
    return stats


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

def compute_consistency(lap_times):
    """
    Consistency % = 100 × (1 − std/mean) on filtered lap times.
    Outliers beyond 2σ are excluded (install laps, incidents).
    Returns None if fewer than 2 clean laps.
    """
    arr = np.array([t for t in lap_times if t and t > 0], dtype=float)
    if len(arr) < 2:
        return None
    mean = arr.mean()
    std = arr.std()
    if std == 0:
        return 100.0
    filtered = arr[np.abs(arr - mean) <= config.OUTLIER_LAP_STD_MULT * std]
    if len(filtered) < 2:
        return None
    score = 100.0 * (1.0 - filtered.std() / filtered.mean())
    return round(max(0.0, min(100.0, score)), 1)


# ---------------------------------------------------------------------------
# Zone detection
# ---------------------------------------------------------------------------

def zero_correct_inline(ig):
    """
    Remove the DC bias from the inline G channel.
    AiM Solo2 devices often have a gravity component if not perfectly levelled.
    We subtract the per-lap mean so zones are relative to steady-state.
    """
    return ig - ig.mean()


def detect_zones(inline_df, lateral_df):
    """
    Classify every 50Hz timestamp as braking / accelerating / cornering / coasting.
    Returns list of {start, end, type, color} dicts (merged consecutive same-zone spans).
    Inline G is zero-corrected before classification to remove mounting offset.
    """
    if inline_df is None or len(inline_df) == 0:
        return []

    times = inline_df['lap_time'].values if 'lap_time' in inline_df.columns else inline_df['time'].values
    ig_raw = inline_df['value'].values
    ig = zero_correct_inline(ig_raw)  # remove mounting/gravity offset

    if lateral_df is not None and len(lateral_df) > 0:
        lat_times = lateral_df['lap_time'].values if 'lap_time' in lateral_df.columns else lateral_df['time'].values
        lg = _interp(times, lat_times, lateral_df['value'].values)
        lg = lg - lg.mean()  # zero-correct lateral too
    else:
        lg = np.zeros_like(ig)

    BT = config.BRAKING_G_THRESHOLD
    AT = config.ACCEL_G_THRESHOLD
    CT = config.CORNERING_G_THRESHOLD

    zone_colors = {
        'braking':      '#e74c3c',
        'accelerating': '#2ecc71',
        'cornering':    '#f39c12',
        'coasting':     '#555555',
    }

    labels = []
    for i_val, l_val in zip(ig, lg):
        if i_val < -BT:
            labels.append('braking')
        elif i_val > AT:
            labels.append('accelerating')
        elif abs(l_val) > CT:
            labels.append('cornering')
        else:
            labels.append('coasting')

    zones = []
    if len(labels) == 0:
        return zones

    cur_zone = labels[0]
    cur_start = float(times[0])
    for i in range(1, len(labels)):
        if labels[i] != cur_zone:
            zones.append({
                'start': round(cur_start, 3),
                'end': round(float(times[i - 1]), 3),
                'type': cur_zone,
                'color': zone_colors[cur_zone],
            })
            cur_zone = labels[i]
            cur_start = float(times[i])
    zones.append({
        'start': round(cur_start, 3),
        'end': round(float(times[-1]), 3),
        'type': cur_zone,
        'color': zone_colors[cur_zone],
    })
    return zones


def zone_percentages(inline_df, lateral_df):
    """Return % of lap time spent in each zone."""
    zones = detect_zones(inline_df, lateral_df)
    if not zones:
        return {'braking': 0, 'accelerating': 0, 'cornering': 0, 'coasting': 100}
    totals = {'braking': 0.0, 'accelerating': 0.0, 'cornering': 0.0, 'coasting': 0.0}
    for z in zones:
        totals[z['type']] += z['end'] - z['start']
    total_time = sum(totals.values())
    if total_time == 0:
        return {k: 0 for k in totals}
    return {k: round(v / total_time * 100, 1) for k, v in totals.items()}


# ---------------------------------------------------------------------------
# Speed histogram
# ---------------------------------------------------------------------------

def speed_histogram(gps_df, bins=20):
    """Return histogram of speed values across the recording."""
    if gps_df is None or len(gps_df) == 0:
        return {'bins': [], 'counts': []}
    speeds = gps_df['speed_mph'].values
    counts, edges = np.histogram(speeds, bins=bins)
    bin_centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
    return {
        'bins': [round(b, 1) for b in bin_centers],
        'counts': counts.tolist(),
    }


# ---------------------------------------------------------------------------
# Lap comparison / delta
# ---------------------------------------------------------------------------

def resample_lap_to_distance(gps_seg, resolution_ft=10.0):
    """
    Resample a GPS lap segment to a uniform distance axis (every resolution_ft feet).
    Returns (distance_arr, time_arr, speed_arr).
    """
    g = compute_distance_ft(gps_seg)
    max_d = g['distance_ft'].max()
    if max_d < resolution_ft:
        return np.array([]), np.array([]), np.array([])
    d_axis = np.arange(0, max_d, resolution_ft)
    t_resampled = np.interp(d_axis, g['distance_ft'].values, g['lap_time'].values)
    s_resampled = np.interp(d_axis, g['distance_ft'].values, g['speed_mph'].values)
    return d_axis, t_resampled, s_resampled


def lap_delta(gps_seg1, gps_seg2, resolution_ft=10.0):
    """
    Compute time delta between two lap GPS segments at uniform distance intervals.
    Positive delta = lap1 is ahead (faster) at that point.
    Returns (distance_arr, delta_arr, lap1_speed, lap2_speed).
    """
    d1, t1, s1 = resample_lap_to_distance(gps_seg1, resolution_ft)
    d2, t2, s2 = resample_lap_to_distance(gps_seg2, resolution_ft)
    if len(d1) == 0 or len(d2) == 0:
        return [], [], [], []
    max_d = min(d1[-1], d2[-1])
    d_common = np.arange(0, max_d, resolution_ft)
    t1_r = np.interp(d_common, d1, t1)
    t2_r = np.interp(d_common, d2, t2)
    s1_r = np.interp(d_common, d1, s1)
    s2_r = np.interp(d_common, d2, s2)
    delta = t2_r - t1_r  # positive = lap2 slower = lap1 is ahead
    return (
        [round(float(v), 1) for v in d_common],
        [round(float(v), 3) for v in delta],
        [round(float(v), 2) for v in s1_r],
        [round(float(v), 2) for v in s2_r],
    )


# ---------------------------------------------------------------------------
# Track map
# ---------------------------------------------------------------------------

def build_track_map(gps_seg, max_pts=None):
    """
    Build track map data from a GPS segment.
    Returns {x_ft, y_ft, speed_mph} arrays, downsampled if needed.
    """
    if gps_seg is None or len(gps_seg) < 2:
        return None
    mp = max_pts or config.TRACK_MAP_MAX_PTS
    lat = gps_seg['lat'].values
    lon = gps_seg['lon'].values
    spd = gps_seg['speed_mph'].values
    x, y = latlon_to_xy_ft(lat, lon)
    if len(x) > mp:
        idx = np.round(np.linspace(0, len(x) - 1, mp)).astype(int)
        x, y, spd = x[idx], y[idx], spd[idx]
    return {
        'x_ft': [round(float(v), 1) for v in x],
        'y_ft': [round(float(v), 1) for v in y],
        'speed_mph': [round(float(v), 2) for v in spd],
    }


# ---------------------------------------------------------------------------
# Replay frame builder
# ---------------------------------------------------------------------------

def build_replay_frames(channels, laps_df, lap_num):
    """
    Build a list of frame dicts resampled to REPLAY_HZ for the specified lap.
    Each frame: {t, x_ft, y_ft, speed_mph, inline_g, lateral_g, vertical_g,
                 yaw_rate, pitch_rate, roll_rate}
    """
    row = laps_df[laps_df['lap'] == lap_num]
    if len(row) == 0:
        return []
    t_start = float(row.iloc[0]['start'])
    t_end = t_start + float(row.iloc[0]['time'])
    dt = 1.0 / config.REPLAY_HZ
    t_axis = np.arange(t_start, t_end, dt)

    def get_values(ch_name, col='value'):
        ch = channels.get(ch_name)
        if ch is None or len(ch) == 0:
            return np.zeros(len(t_axis))
        return _interp(t_axis, ch['time'].values, ch[col].values)

    gps = channels.get('gps')
    if gps is not None and len(gps) > 1:
        lat = _interp(t_axis, gps['time'].values, gps['lat'].values)
        lon = _interp(t_axis, gps['time'].values, gps['lon'].values)
        x, y = latlon_to_xy_ft(lat, lon)
        speed = _interp(t_axis, gps['time'].values, gps['speed_mph'].values)
    else:
        x = y = speed = np.zeros(len(t_axis))

    inline_g    = get_values('inline_acc')
    lateral_g   = get_values('lateral_acc')
    vertical_g  = get_values('vertical_acc')
    yaw_rate    = get_values('yaw_rate')
    pitch_rate  = get_values('pitch_rate')
    roll_rate   = get_values('roll_rate')

    frames = []
    for i, t in enumerate(t_axis):
        frames.append({
            't':           round(float(t - t_start), 3),
            'x_ft':        round(float(x[i]), 1),
            'y_ft':        round(float(y[i]), 1),
            'speed_mph':   round(float(speed[i]), 2),
            'inline_g':    round(float(inline_g[i]), 3),
            'lateral_g':   round(float(lateral_g[i]), 3),
            'vertical_g':  round(float(vertical_g[i]), 3),
            'yaw_rate':    round(float(yaw_rate[i]), 2),
            'pitch_rate':  round(float(pitch_rate[i]), 2),
            'roll_rate':   round(float(roll_rate[i]), 2),
        })
    return frames


# ---------------------------------------------------------------------------
# Full session analysis (used after all recordings are ingested)
# ---------------------------------------------------------------------------

def aggregate_session_stats(all_laps):
    """
    Given a list of lap dicts (from DB), compute session-level aggregates.
    Returns dict with best_lap_time, avg_lap_time, consistency_pct, max_speed_mph.
    """
    times = [l['lap_time'] for l in all_laps if l['lap_time'] and l['lap_time'] > 0]
    speeds = [l['max_speed'] for l in all_laps if l['max_speed']]
    if not times:
        return {}
    best = min(times)
    avg = sum(times) / len(times)
    consistency = compute_consistency(times)
    max_spd = max(speeds) if speeds else None
    return {
        'best_lap_time': round(best, 3),
        'avg_lap_time': round(avg, 3),
        'consistency_pct': consistency,
        'max_speed_mph': round(max_spd, 2) if max_spd else None,
        'lap_count': len(times),
    }
