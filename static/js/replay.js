/* Live session replay — animation engine with handling flag detection */

const SESSION_ID = parseInt(document.getElementById('session-id').dataset.id);

let frames = [];
let frameIndex = 0;
let isPlaying = false;
let playSpeed = 1.0;
let animHandle = null;
let lastWallTime = null;
let trackInitialized = false;
const WINDOW_SECS = 5; // scrolling trace window

// Handling state
let handlingEvents = [];   // [{frameIdx, type, t, severity}]
let currentFlag = null;    // 'understeer' | 'oversteer' | null
let flagHoldFrames = 0;    // keep flag visible for a minimum duration

// Current recording context for lap nav
let currentRecordingId = null;
let availableLaps = [];

// ── Understeer / Oversteer Detection ──────────────────────────────────────────
// Method: compare actual yaw rate to the "steady-state" yaw rate expected for
// the current speed and lateral G.  If actual << expected → understeer (front
// lost grip).  If actual >> expected → oversteer (rear stepped out).
//
//   expected_yaw (deg/s) = |lat_g| * 9.81 / speed_mps * RAD_TO_DEG
//
// We only fire inside a corner (|lat_g| > 0.35g, speed > 8 mph) and require
// the ratio to stay outside the band for ≥ 3 consecutive frames to avoid noise.

const US_RATIO_THRESHOLD = 0.50;   // actual / expected < this → understeer
const OS_RATIO_THRESHOLD = 1.75;   // actual / expected > this → oversteer
const MIN_LAT_G_FOR_FLAG = 0.35;   // only flag inside real corners
const MIN_SPEED_MPH = 8;           // ignore very low speed (pit exit, stalls)
const MIN_FRAMES_SUSTAINED = 3;    // must last at least 3 frames (~150ms)

function detectHandlingEvents(framesArr) {
  const events = [];
  let runType = null;
  let runStart = 0;
  let runLen = 0;

  for (let i = 0; i < framesArr.length; i++) {
    const f = framesArr[i];
    const latG = Math.abs(f.lateral_g);
    const speedMph = f.speed_mph;
    const speedMps = speedMph * 0.44704;

    if (latG < MIN_LAT_G_FOR_FLAG || speedMph < MIN_SPEED_MPH) {
      if (runLen >= MIN_FRAMES_SUSTAINED && runType) {
        events.push({ frameIdx: runStart, t: framesArr[runStart].t,
                      type: runType, len: runLen,
                      severity: runLen >= 10 ? 'high' : runLen >= 6 ? 'medium' : 'low' });
      }
      runType = null; runLen = 0;
      continue;
    }

    const expectedYaw = (latG * 9.81 / Math.max(speedMps, 0.5)) * 57.296; // deg/s
    const actualYaw = Math.abs(f.yaw_rate);
    const ratio = actualYaw / Math.max(expectedYaw, 1);

    let thisType = null;
    if (ratio < US_RATIO_THRESHOLD) thisType = 'understeer';
    else if (ratio > OS_RATIO_THRESHOLD) thisType = 'oversteer';

    if (thisType === runType && thisType !== null) {
      runLen++;
    } else {
      if (runLen >= MIN_FRAMES_SUSTAINED && runType) {
        events.push({ frameIdx: runStart, t: framesArr[runStart].t,
                      type: runType, len: runLen,
                      severity: runLen >= 10 ? 'high' : runLen >= 6 ? 'medium' : 'low' });
      }
      runType = thisType;
      runStart = i;
      runLen = thisType ? 1 : 0;
    }
  }
  // Flush final run
  if (runLen >= MIN_FRAMES_SUSTAINED && runType) {
    events.push({ frameIdx: runStart, t: framesArr[runStart].t,
                  type: runType, len: runLen,
                  severity: runLen >= 10 ? 'high' : runLen >= 6 ? 'medium' : 'low' });
  }
  return events;
}

function buildHandlingEventLog(events) {
  const list = document.getElementById('handling-events-list');
  const noMsg = document.getElementById('no-events-msg');
  // Remove all existing event items
  list.querySelectorAll('.event-item').forEach(el => el.remove());

  if (events.length === 0) {
    noMsg.classList.remove('d-none');
    return;
  }
  noMsg.classList.add('d-none');

  events.forEach(ev => {
    const isUS = ev.type === 'understeer';
    const color = isUS ? '#3498db' : '#e74c3c';
    const icon  = isUS ? '🔵' : '🔴';
    const label = isUS ? 'Understeer' : 'Oversteer';
    const sevLabel = ev.severity === 'high' ? '●●●' : ev.severity === 'medium' ? '●●○' : '●○○';
    const durationMs = Math.round(ev.len * (1000 / 20));

    const item = document.createElement('button');
    item.className = 'event-item list-group-item list-group-item-action bg-dark border-secondary py-2 px-3 d-flex align-items-center gap-3';
    item.innerHTML = `
      <span style="font-size:1.1rem">${icon}</span>
      <div class="flex-fill">
        <span class="fw-semibold" style="color:${color}">${label}</span>
        <span class="ms-2 small text-secondary">@ ${ev.t.toFixed(2)}s</span>
        <span class="ms-2 small" style="color:${color};opacity:.7">${sevLabel}</span>
      </div>
      <small class="text-secondary">${durationMs}ms</small>
    `;
    item.addEventListener('click', () => {
      stopPlayback();
      frameIndex = ev.frameIdx;
      renderFrame(ev.frameIdx);
    });
    list.appendChild(item);
  });
}

function getFlagAtFrame(idx) {
  // Find the first event that contains this frame index
  for (const ev of handlingEvents) {
    if (idx >= ev.frameIdx && idx < ev.frameIdx + ev.len) {
      return ev;
    }
  }
  return null;
}

function showFlag(ev) {
  const banner = document.getElementById('handling-flag');
  const title  = document.getElementById('flag-title');
  const desc   = document.getElementById('flag-desc');
  const icon   = document.getElementById('flag-icon');

  if (!ev) {
    if (flagHoldFrames > 0) { flagHoldFrames--; return; }
    banner.classList.add('d-none');
    currentFlag = null;
    return;
  }

  const isUS = ev.type === 'understeer';
  banner.classList.remove('d-none');
  banner.style.background = isUS
    ? 'linear-gradient(90deg,rgba(52,152,219,.25),rgba(52,152,219,.08))'
    : 'linear-gradient(90deg,rgba(231,76,60,.28),rgba(231,76,60,.08))';
  banner.style.border = `1px solid ${isUS ? 'rgba(52,152,219,.4)' : 'rgba(231,76,60,.4)'}`;
  icon.textContent  = isUS ? '🔵' : '🔴';
  title.textContent = isUS ? 'UNDERSTEER' : 'OVERSTEER';
  title.style.color = isUS ? '#3498db' : '#e74c3c';
  desc.textContent  = isUS
    ? 'Front tires losing grip — kart pushing wide. Try less entry speed or later apex.'
    : 'Rear tires stepping out — kart rotating too much. Reduce throttle or open steering earlier.';
  currentFlag = ev.type;
  flagHoldFrames = 8; // keep visible for ~8 frames after event ends
}

// ── Load session info ──────────────────────────────────────────────────────────
async function initReplay() {
  const sess = await apiFetch(`/api/sessions/${SESSION_ID}`);
  const kartColor = sess.kart_color || '#00d4aa';
  document.getElementById('replay-title').textContent = `Replay — ${sess.name}`;
  const badge = document.getElementById('replay-kart-badge');
  badge.textContent = sess.kart_name;
  badge.style.background = kartColor;
  badge.style.color = '#000';

  const recSelect = document.getElementById('replay-recording-select');
  const recs = sess.recordings || [];
  if (recs.length === 0) {
    recSelect.innerHTML = '<option>No recordings</option>';
    return;
  }
  recs.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.id;
    opt.textContent = r.name;
    recSelect.appendChild(opt);
  });
  recSelect.addEventListener('change', () => loadRecordingLaps(parseInt(recSelect.value)));
  await loadRecordingLaps(recs[0].id);
}

async function loadRecordingLaps(recordingId) {
  currentRecordingId = recordingId;
  const lapSelect = document.getElementById('replay-lap-select');
  lapSelect.innerHTML = '<option>Loading…</option>';
  try {
    const data = await apiFetch(`/api/replay/${recordingId}?lap=1`);
    availableLaps = data.available_laps || [1];
    lapSelect.innerHTML = '';
    availableLaps.forEach(l => {
      const opt = document.createElement('option');
      opt.value = l;
      opt.textContent = `Lap ${l}`;
      lapSelect.appendChild(opt);
    });
    // Remove old listener before adding new
    lapSelect.onchange = () => loadFrames(recordingId, parseInt(lapSelect.value));
    updateLapNavButtons();
    await loadFrames(recordingId, availableLaps[0]);
  } catch (e) {
    lapSelect.innerHTML = '<option>Error</option>';
  }
}

async function loadFrames(recordingId, lap) {
  stopPlayback();
  frames = [];
  frameIndex = 0;
  handlingEvents = [];
  currentFlag = null;
  flagHoldFrames = 0;
  trackInitialized = false;
  document.getElementById('replay-scrubber').value = 0;
  document.getElementById('handling-flag').classList.add('d-none');

  const data = await apiFetch(`/api/replay/${recordingId}?lap=${lap}`);
  frames = data.frames || [];

  if (frames.length === 0) return;

  const scrubber = document.getElementById('replay-scrubber');
  scrubber.max = frames.length - 1;
  document.getElementById('replay-time-total').textContent = frames[frames.length - 1].t.toFixed(3) + 's';

  // Detect handling events
  handlingEvents = detectHandlingEvents(frames);
  buildHandlingEventLog(handlingEvents);

  initTrackMap();
  initSpeedGauge();
  initGGLive();
  initScrollingTraces();
  renderFrame(0);
}

// ── Lap navigation ─────────────────────────────────────────────────────────────
function updateLapNavButtons() {
  const lapSelect = document.getElementById('replay-lap-select');
  const currentIdx = availableLaps.indexOf(parseInt(lapSelect.value));
  document.getElementById('replay-prev-lap').disabled = currentIdx <= 0;
  document.getElementById('replay-next-lap').disabled = currentIdx >= availableLaps.length - 1;
}

document.getElementById('replay-prev-lap').addEventListener('click', () => {
  const lapSelect = document.getElementById('replay-lap-select');
  const currentIdx = availableLaps.indexOf(parseInt(lapSelect.value));
  if (currentIdx > 0) {
    lapSelect.value = availableLaps[currentIdx - 1];
    updateLapNavButtons();
    loadFrames(currentRecordingId, availableLaps[currentIdx - 1]);
  }
});

document.getElementById('replay-next-lap').addEventListener('click', () => {
  const lapSelect = document.getElementById('replay-lap-select');
  const currentIdx = availableLaps.indexOf(parseInt(lapSelect.value));
  if (currentIdx < availableLaps.length - 1) {
    lapSelect.value = availableLaps[currentIdx + 1];
    updateLapNavButtons();
    loadFrames(currentRecordingId, availableLaps[currentIdx + 1]);
  }
});

// ── Playback controls ──────────────────────────────────────────────────────────
document.getElementById('replay-play').addEventListener('click', togglePlayback);
document.getElementById('replay-restart').addEventListener('click', () => {
  stopPlayback();
  frameIndex = 0;
  renderFrame(0);
});

document.querySelectorAll('.speed-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    playSpeed = parseFloat(btn.dataset.speed);
  });
});

document.getElementById('replay-scrubber').addEventListener('input', e => {
  stopPlayback();
  frameIndex = parseInt(e.target.value);
  renderFrame(frameIndex);
});

function togglePlayback() {
  if (isPlaying) stopPlayback();
  else startPlayback();
}

function startPlayback() {
  if (frames.length === 0) return;
  if (frameIndex >= frames.length - 1) frameIndex = 0;
  isPlaying = true;
  lastWallTime = performance.now();
  document.getElementById('replay-play').innerHTML = '<i class="bi bi-pause-fill"></i> Pause';
  document.getElementById('replay-play').classList.replace('btn-success', 'btn-warning');
  animHandle = requestAnimationFrame(animLoop);
}

function stopPlayback() {
  isPlaying = false;
  if (animHandle) { cancelAnimationFrame(animHandle); animHandle = null; }
  document.getElementById('replay-play').innerHTML = '<i class="bi bi-play-fill"></i> Play';
  document.getElementById('replay-play').classList.replace('btn-warning', 'btn-success');
}

function animLoop(now) {
  if (!isPlaying) return;
  const elapsed = (now - lastWallTime) / 1000;
  lastWallTime = now;
  const REPLAY_HZ = 20;
  const frameStep = elapsed * playSpeed * REPLAY_HZ;
  frameIndex = Math.min(frameIndex + frameStep, frames.length - 1);
  renderFrame(Math.floor(frameIndex));
  if (frameIndex >= frames.length - 1) { stopPlayback(); return; }
  animHandle = requestAnimationFrame(animLoop);
}

// ── Render a single frame ──────────────────────────────────────────────────────
function renderFrame(idx) {
  if (!frames.length) return;
  idx = Math.max(0, Math.min(Math.floor(idx), frames.length - 1));
  const f = frames[idx];

  document.getElementById('replay-scrubber').value = idx;
  document.getElementById('replay-time-current').textContent = f.t.toFixed(3) + 's';

  updateTrackDot(f, idx);
  updateSpeedGauge(f.speed_mph);
  updateGGDot(f.lateral_g, f.inline_g);
  updateScrollingTraces(idx);

  // Handling flag
  const ev = getFlagAtFrame(idx);
  showFlag(ev);
}

// ── Track Map ──────────────────────────────────────────────────────────────────
let trailLength = 80;

function initTrackMap() {
  if (!frames.length) return;
  const allX = frames.map(f => f.x_ft);
  const allY = frames.map(f => f.y_ft);

  const bgTrace = {
    x: allX, y: allY, type: 'scatter', mode: 'markers',
    marker: { size: 2, color: '#333' },
    hoverinfo: 'none', showlegend: false,
  };
  const trailTrace = {
    x: [allX[0]], y: [allY[0]], type: 'scatter', mode: 'lines',
    line: { color: '#00d4aa', width: 4 },
    hoverinfo: 'none', showlegend: false,
  };
  const dotTrace = {
    x: [allX[0]], y: [allY[0]], type: 'scatter', mode: 'markers',
    marker: { size: 14, color: '#00d4aa', symbol: 'circle',
              line: { color: '#fff', width: 2 } },
    hoverinfo: 'none', showlegend: false,
  };
  // Flag marker (hidden initially)
  const flagTrace = {
    x: [], y: [], type: 'scatter', mode: 'markers',
    marker: { size: 18, color: 'rgba(0,0,0,0)', symbol: 'circle',
              line: { color: 'rgba(0,0,0,0)', width: 3 } },
    hoverinfo: 'none', showlegend: false,
  };

  Plotly.react('replay-track-map', [bgTrace, trailTrace, dotTrace, flagTrace],
    basePlotLayout({
      xaxis: { scaleanchor: 'y', scaleratio: 1, gridcolor: GRID_COLOR,
               zeroline: false, showticklabels: false },
      yaxis: { gridcolor: GRID_COLOR, zeroline: false, showticklabels: false },
      margin: { t: 5, l: 5, r: 5, b: 5 },
    }), PLOT_CONFIG);

  trackInitialized = true;
}

function updateTrackDot(f, idx) {
  if (!trackInitialized) return;
  const start = Math.max(0, idx - trailLength);
  const trail = frames.slice(start, idx + 1);
  const trailX = trail.map(fr => fr.x_ft);
  const trailY = trail.map(fr => fr.y_ft);
  const trailSpd = trail.map(fr => fr.speed_mph);
  const maxSpd = Math.max(...frames.map(fr => fr.speed_mph), 1);
  const trailColors = trailSpd.map(s => {
    const r = Math.round((s / maxSpd) * 220);
    const b = Math.round((1 - s / maxSpd) * 200 + 55);
    return `rgb(${r},80,${b})`;
  });

  // Check handling state for dot color
  const ev = getFlagAtFrame(idx);
  const dotColor = ev
    ? (ev.type === 'understeer' ? '#3498db' : '#e74c3c')
    : '#00d4aa';

  Plotly.restyle('replay-track-map', {
    x: [trailX, [f.x_ft], []],
    y: [trailY, [f.y_ft], []],
    'marker.color': [undefined, [dotColor], []],
  }, [1, 2, 3]);
}

// ── Speed Gauge ────────────────────────────────────────────────────────────────
function initSpeedGauge() {
  const maxSpd = Math.max(...frames.map(f => f.speed_mph), 60);
  Plotly.react('replay-speed-gauge', [{
    type: 'indicator', mode: 'gauge+number',
    value: 0,
    number: { suffix: ' mph', font: { size: 28, color: '#00d4aa' } },
    gauge: {
      axis: { range: [0, Math.ceil(maxSpd / 10) * 10], tickcolor: '#666' },
      bar: { color: '#00d4aa' },
      bgcolor: '#111',
      bordercolor: '#333',
      steps: [
        { range: [0, maxSpd * 0.4], color: '#1a2a1a' },
        { range: [maxSpd * 0.4, maxSpd * 0.75], color: '#1a3a1a' },
        { range: [maxSpd * 0.75, maxSpd * 1.1], color: '#2a3a1a' },
      ],
    },
  }], {
    paper_bgcolor: PAPER_BG, font: { color: FONT_COLOR },
    margin: { t: 30, l: 20, r: 20, b: 20 },
  }, PLOT_CONFIG);
}

function updateSpeedGauge(mph) {
  Plotly.restyle('replay-speed-gauge', { value: [mph] }, [0]);
}

// ── Live G-G dot ───────────────────────────────────────────────────────────────
function initGGLive() {
  const circle = (r, color) => {
    const t = Array.from({ length: 100 }, (_, i) => (2 * Math.PI * i) / 99);
    return { x: t.map(a => r * Math.cos(a)), y: t.map(a => r * Math.sin(a)),
             type: 'scatter', mode: 'lines', line: { color, width: 1, dash: 'dot' },
             hoverinfo: 'none', showlegend: false };
  };
  const dotTrace = {
    x: [0], y: [0], type: 'scatter', mode: 'markers',
    marker: { size: 14, color: '#f39c12', symbol: 'circle',
              line: { color: '#fff', width: 1.5 } },
    showlegend: false,
  };
  Plotly.react('replay-gg-live',
    [circle(1.5, 'rgba(255,100,100,0.25)'), circle(1, 'rgba(255,255,255,0.15)'), dotTrace],
    basePlotLayout({
      xaxis: { title: 'Lateral G', range: [-2, 2], scaleanchor: 'y', scaleratio: 1,
               gridcolor: GRID_COLOR, zeroline: true, zerolinecolor: '#333' },
      yaxis: { title: 'Longitudinal G', range: [-2, 2], gridcolor: GRID_COLOR,
               zeroline: true, zerolinecolor: '#333' },
      margin: { t: 10, l: 55, r: 10, b: 40 },
    }), PLOT_CONFIG);
}

function updateGGDot(lat, lon) {
  // Color the G-G dot based on handling state
  const ev = getFlagAtFrame(Math.floor(frameIndex));
  const color = ev
    ? (ev.type === 'understeer' ? '#3498db' : '#e74c3c')
    : '#f39c12';
  Plotly.restyle('replay-gg-live', { x: [[lat]], y: [[lon]], 'marker.color': [color] }, [2]);
}

// ── Scrolling traces ───────────────────────────────────────────────────────────
function initScrollingTraces() {
  const commonLayout = (yTitle) => basePlotLayout({
    yaxis: { title: yTitle, gridcolor: GRID_COLOR },
    xaxis: { title: 'Time (s)', gridcolor: GRID_COLOR },
    margin: { t: 5, l: 55, r: 5, b: 35 },
    hovermode: false,
  });

  Plotly.react('replay-speed-trace',
    [{ x: [], y: [], type: 'scatter', mode: 'lines', line: { color: '#00d4aa', width: 2 } }],
    commonLayout('Speed (mph)'), PLOT_CONFIG);

  Plotly.react('replay-inlineg-trace',
    [{ x: [], y: [], type: 'scatter', mode: 'lines', line: { color: '#e74c3c', width: 2 } }],
    commonLayout('Long G'), PLOT_CONFIG);

  Plotly.react('replay-lateralg-trace',
    [{ x: [], y: [], type: 'scatter', mode: 'lines', line: { color: '#f39c12', width: 2 } }],
    commonLayout('Lat G'), PLOT_CONFIG);
}

function updateScrollingTraces(idx) {
  if (!frames.length) return;
  const REPLAY_HZ = 20;
  const windowFrames = WINDOW_SECS * REPLAY_HZ;
  const start = Math.max(0, idx - windowFrames);
  const slice = frames.slice(start, idx + 1);

  const times    = slice.map(f => f.t);
  const speeds   = slice.map(f => f.speed_mph);
  const inlineGs = slice.map(f => f.inline_g);
  const lateralGs = slice.map(f => f.lateral_g);

  Plotly.restyle('replay-speed-trace',   { x: [times], y: [speeds] },    [0]);
  Plotly.restyle('replay-inlineg-trace', { x: [times], y: [inlineGs] },  [0]);
  Plotly.restyle('replay-lateralg-trace',{ x: [times], y: [lateralGs] }, [0]);
}

// ── Init ───────────────────────────────────────────────────────────────────────
initReplay().catch(console.error);
