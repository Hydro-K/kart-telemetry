import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'telemetry.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
MAX_UPLOAD_MB = 100

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'phi3:mini')
OLLAMA_TIMEOUT = 300  # 5 min — first load of a large model can take 10-30s before tokens start

# Unit conversion constants
MS_TO_MPH = 2.23694
M_TO_FT = 3.28084

# Analysis thresholds (in g)
BRAKING_G_THRESHOLD = 0.3
ACCEL_G_THRESHOLD = 0.3
CORNERING_G_THRESHOLD = 0.3
OUTLIER_LAP_STD_MULT = 2.0

# Minimum lap time to count as a valid racing lap (filters install/warmup laps)
# AiM records a partial "lap 1" whenever the logger starts mid-lap
MIN_LAP_TIME_S = 30.0

# GPS quality filter
MAX_GPS_ACCURACY_M = 2.0

# Replay resampling rate (Hz)
REPLAY_HZ = 20

# Track map downsampling (max GPS points per lap for rendering)
TRACK_MAP_MAX_PTS = 1000
