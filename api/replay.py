"""
Replay endpoint — returns pre-merged frame data for a single lap,
resampled to REPLAY_HZ for smooth client-side animation.
"""

import json
import pandas as pd
from flask import Blueprint, request, jsonify
from database.db import get_db
from processing.analyzer import build_replay_frames

replay_bp = Blueprint('replay', __name__)


def _load_channels(db, recording_id):
    rows = db.execute(
        "SELECT channel, data_json FROM telemetry WHERE recording_id=?",
        (recording_id,)
    ).fetchall()
    channels = {}
    for row in rows:
        data = json.loads(row['data_json'])
        if data:
            channels[row['channel']] = pd.DataFrame(data)
    return channels


@replay_bp.route('/replay/<int:recording_id>', methods=['GET'])
def get_replay(recording_id):
    lap = request.args.get('lap', type=int, default=1)
    db = get_db()

    rec = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
    if not rec:
        db.close()
        return jsonify({'error': 'Recording not found'}), 404

    channels = _load_channels(db, recording_id)
    laps_df = channels.get('laps')
    if laps_df is None:
        db.close()
        return jsonify({'error': 'No lap data'}), 404

    # Get all laps for this recording
    all_laps = laps_df['lap'].tolist()

    db.close()

    frames = build_replay_frames(channels, laps_df, lap)
    return jsonify({
        'recording_id': recording_id,
        'recording_name': rec['name'],
        'lap': lap,
        'available_laps': [int(l) for l in all_laps],
        'frame_count': len(frames),
        'frames': frames,
    })


@replay_bp.route('/sessions/<int:session_id>/recordings', methods=['GET'])
def list_recordings(session_id):
    """List all recordings for a session with their lap counts."""
    db = get_db()
    recs = db.execute(
        "SELECT * FROM recordings WHERE session_id=? ORDER BY uploaded_at ASC",
        (session_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in recs])
