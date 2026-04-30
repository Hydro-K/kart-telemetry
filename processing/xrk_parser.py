"""
Parse AiM Solo2 native XRK binary files using the libxrk package.
Returns the same channel dict format as csv_parser.parse_csv_folder().

libxrk timecodes are in milliseconds — convert to seconds throughout.
GPS Speed from XRK is in m/s — convert to mph.
GPS Altitude is in meters — convert to feet.
"""

import os
import numpy as np
import pandas as pd
import config


def parse_xrk(xrk_path):
    """
    Parse an XRK file. Returns (recording_name, channels_dict).
    Raises ImportError if libxrk is not installed.
    Raises Exception if the file cannot be parsed.
    """
    try:
        from libxrk import aim_xrk
    except ImportError as e:
        raise ImportError(
            "libxrk package not found. Install with: pip install libxrk"
        ) from e

    recording_name = os.path.splitext(os.path.basename(xrk_path))[0]
    log = aim_xrk(xrk_path)
    chs = log.channels  # dict: channel_name -> PyArrow Table

    channels = {}

    # ---------------------------------------------------------------------------
    # IMU channels (50Hz, timecodes in ms → seconds)
    # ---------------------------------------------------------------------------
    imu_map = {
        'InlineAcc':  'inline_acc',
        'LateralAcc': 'lateral_acc',
        'VerticalAcc': 'vertical_acc',
        'PitchRate':  'pitch_rate',
        'RollRate':   'roll_rate',
        'YawRate':    'yaw_rate',
        # alternate names sometimes seen in older XRK files
        'Inline Acc':  'inline_acc',
        'Lateral Acc': 'lateral_acc',
        'Vertical Acc': 'vertical_acc',
        'Pitch Rate':  'pitch_rate',
        'Roll Rate':   'roll_rate',
        'Yaw Rate':    'yaw_rate',
    }
    for ch_name, key in imu_map.items():
        if ch_name in chs:
            tbl = chs[ch_name]
            times_s = tbl.column('timecodes').to_pylist()
            values = tbl.column(ch_name).to_pylist()
            times_s = [t / 1000.0 for t in times_s]  # ms → s
            channels[key] = pd.DataFrame({'time': times_s, 'value': values})

    # ---------------------------------------------------------------------------
    # Battery
    # ---------------------------------------------------------------------------
    for batt_name in ('Internal Battery', 'Battery Voltage'):
        if batt_name in chs:
            tbl = chs[batt_name]
            times_s = [t / 1000.0 for t in tbl.column('timecodes').to_pylist()]
            values = tbl.column(batt_name).to_pylist()
            channels['battery'] = pd.DataFrame({'time': times_s, 'value': values})
            break

    # ---------------------------------------------------------------------------
    # GPS — combine individual channels into a single DataFrame
    # ---------------------------------------------------------------------------
    gps_ch_map = {
        'GPS Speed': 'speed_ms',
        'GPS Latitude': 'lat',
        'GPS Longitude': 'lon',
        'GPS Altitude': 'alt_m',
        'GPS_Position_Accuracy': 'accuracy',
    }
    gps_parts = {}
    gps_times = None
    for ch_name, col_key in gps_ch_map.items():
        if ch_name in chs:
            tbl = chs[ch_name]
            t = [x / 1000.0 for x in tbl.column('timecodes').to_pylist()]
            v = tbl.column(ch_name).to_pylist()
            gps_parts[col_key] = {'time': t, 'value': v}
            if gps_times is None:
                gps_times = t

    if gps_times and 'lat' in gps_parts and 'lon' in gps_parts and 'speed_ms' in gps_parts:
        lat_v = gps_parts['lat']['value']
        lon_v = gps_parts['lon']['value']
        spd_v = gps_parts['speed_ms']['value']
        alt_v = gps_parts.get('alt_m', {}).get('value', [0.0] * len(lat_v))
        acc_v = gps_parts.get('accuracy', {}).get('value', [0.0] * len(lat_v))

        # All GPS channels share the same timecodes — safe to zip directly
        n = min(len(gps_times), len(lat_v), len(lon_v), len(spd_v))
        gps_df = pd.DataFrame({
            'time':      gps_times[:n],
            'lat':       lat_v[:n],
            'lon':       lon_v[:n],
            'speed_mph': [s * config.MS_TO_MPH for s in spd_v[:n]],
            'alt_ft':    [a * config.M_TO_FT for a in alt_v[:n]],
            'accuracy':  acc_v[:n],
        })
        # Apply GPS accuracy filter
        if 'accuracy' in gps_df.columns:
            gps_df = gps_df[gps_df['accuracy'] <= config.MAX_GPS_ACCURACY_M].copy()
        channels['gps'] = gps_df

    # ---------------------------------------------------------------------------
    # Laps — from log.laps PyArrow Table
    # ---------------------------------------------------------------------------
    try:
        laps_tbl = log.laps
        nums = laps_tbl.column('num').to_pylist()
        starts = laps_tbl.column('start_time').to_pylist()
        ends = laps_tbl.column('end_time').to_pylist()
        lap_rows = []
        for i, (num, start_ms, end_ms) in enumerate(zip(nums, starts, ends)):
            # AiM typically outputs lap num 0 as the "outlap" before timing starts
            # Renumber to 1-based
            lap_rows.append({
                'run':   1,
                'lap':   i + 1,
                'split': 0,
                'start': start_ms / 1000.0,   # ms → s
                'time':  (end_ms - start_ms) / 1000.0,
            })
        if lap_rows:
            channels['laps'] = pd.DataFrame(lap_rows)
    except Exception:
        pass

    return recording_name, channels
