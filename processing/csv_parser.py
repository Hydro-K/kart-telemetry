"""
Parse AiM Solo2 CSV export folders.

Each folder contains exactly 10 CSV files:
  InlineAcc.csv, LateralAcc.csv, VerticalAcc.csv,
  PitchRate.csv, RollRate.csv, YawRate.csv,
  Internal Battery.csv, _GPS.csv, _GPS_o.csv,
  _laps_and_splits.csv

CSV format: row 0 = headers, row 1 = units (skipped), row 2+ = data.
All outputs use US customary units (mph, feet).
"""

import os
import zipfile
import tempfile
import shutil
import pandas as pd
import config

_CHANNEL_FILES = {
    'inline_acc': 'InlineAcc.csv',
    'lateral_acc': 'LateralAcc.csv',
    'vertical_acc': 'VerticalAcc.csv',
    'pitch_rate': 'PitchRate.csv',
    'roll_rate': 'RollRate.csv',
    'yaw_rate': 'YawRate.csv',
    'battery': 'Internal Battery.csv',
    'gps': '_GPS_o.csv',       # use 20Hz high-res
    'gps_10hz': '_GPS.csv',
    'laps': '_laps_and_splits.csv',
}


def _read_aim_csv(filepath):
    """Read an AiM CSV file, skipping the units row (row index 1)."""
    df = pd.read_csv(filepath, skiprows=[1], skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    return df


def _find_csv_root(extract_dir):
    """
    Find the directory containing InlineAcc.csv within an extracted ZIP.
    Handles both flat ZIPs and ZIPs with a named subfolder.
    """
    for root, _dirs, files in os.walk(extract_dir):
        if 'InlineAcc.csv' in files:
            return root
    # Fallback: look for _laps_and_splits.csv
    for root, _dirs, files in os.walk(extract_dir):
        if '_laps_and_splits.csv' in files:
            return root
    return extract_dir


def parse_csv_folder(folder_path):
    """
    Parse a single AiM CSV export folder.
    Returns dict of DataFrames keyed by channel name.
    GPS speed is converted to mph; altitude and distances to feet.
    """
    channels = {}

    # --- Acceleration and rate channels (time, value) ---
    for key in ('inline_acc', 'lateral_acc', 'vertical_acc',
                'pitch_rate', 'roll_rate', 'yaw_rate', 'battery'):
        fname = _CHANNEL_FILES[key]
        fpath = os.path.join(folder_path, fname)
        if os.path.exists(fpath):
            try:
                df = _read_aim_csv(fpath)
                df.columns = ['time', 'value']
                df = df.dropna().astype(float)
                channels[key] = df
            except Exception:
                pass

    # --- GPS (20Hz high-res) ---
    gps_path = os.path.join(folder_path, _CHANNEL_FILES['gps'])
    if not os.path.exists(gps_path):
        gps_path = os.path.join(folder_path, _CHANNEL_FILES['gps_10hz'])
    if os.path.exists(gps_path):
        try:
            df = _read_aim_csv(gps_path)
            df.columns = [c.strip() for c in df.columns]
            # Rename to standard names
            col_map = {
                df.columns[0]: 'time',
                df.columns[1]: 'itow',
                df.columns[2]: 'lat',
                df.columns[3]: 'lon',
                df.columns[4]: 'alt_m',
                df.columns[5]: 'speed_ms',
                df.columns[6]: 'accuracy',
            }
            df = df.rename(columns=col_map)
            df = df.dropna().astype(float)
            # Filter poor GPS fixes
            df = df[df['accuracy'] <= config.MAX_GPS_ACCURACY_M].copy()
            # Convert units
            df['speed_mph'] = df['speed_ms'] * config.MS_TO_MPH
            df['alt_ft'] = df['alt_m'] * config.M_TO_FT
            channels['gps'] = df
        except Exception:
            pass

    # --- Laps ---
    laps_path = os.path.join(folder_path, _CHANNEL_FILES['laps'])
    if os.path.exists(laps_path):
        try:
            df = _read_aim_csv(laps_path)
            df.columns = [c.strip() for c in df.columns]
            # Normalize column names regardless of case/spacing
            df.columns = ['run', 'lap', 'split', 'start', 'time']
            df = df.dropna().astype(float)
            channels['laps'] = df
        except Exception:
            pass

    return channels


def parse_zip(zip_path):
    """
    Extract a ZIP containing an AiM CSV export folder, parse it, and clean up.
    Returns (folder_name, channels_dict).
    """
    tmp_dir = tempfile.mkdtemp(dir=config.UPLOAD_DIR)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmp_dir)
        csv_root = _find_csv_root(tmp_dir)
        folder_name = os.path.basename(csv_root.rstrip('/\\'))
        channels = parse_csv_folder(csv_root)
        return folder_name, channels
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
