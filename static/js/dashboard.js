/* Main analysis dashboard — all 15 charts */

const SESSION_ID = parseInt(document.getElementById('session-id').dataset.id);
let overviewData = null;
let selectedLap = null;
let xAxisMode = 'time'; // 'time' or 'distance'

// ── Plotly chart helpers ──
function lineTrace(x, y, name, color, width = 2) {
  return { x, y, name, type: 'scatter', mode: 'lines',
    line: { color, width }, hovertemplate: `%{y}<extra>${name}</extra>` };
}

function plotChart(divId, traces, layoutOverrides = {}, height = null) {
  const el = document.getElementById(divId);
  if (!el) return;
  if (height) el.style.height = height + 'px';
  const layout = basePlotLayout(layoutOverrides);
  Plotly.react(divId, traces, layout, PLOT_CONFIG);
}

// ── Load overview ──
async function loadOverview() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/overview`);
  overviewData = data;

  // Session header
  const sess = await apiFetch(`/api/sessions/${SESSION_ID}`);
  const kartColor = sess.kart_color || '#888';
  const badge = document.getElementById('session-kart-badge');
  badge.textContent = sess.kart_name;
  badge.style.background = kartColor;
  badge.style.color = '#000';
  document.getElementById('session-title').textContent = sess.name;

  // Stat cards
  document.getElementById('stat-best-lap').textContent = data.best_lap_formatted || '--:--';
  document.getElementById('stat-avg-lap').textContent = data.avg_lap_formatted || '--:--';
  document.getElementById('stat-laps').textContent = data.lap_count || 0;
  const cons = data.consistency_pct;
  document.getElementById('stat-consistency').textContent = cons != null ? `${cons.toFixed(1)}%` : '--%';
  document.getElementById('stat-top-speed').textContent = data.max_speed_mph ? `${data.max_speed_mph.toFixed(1)} mph` : '-- mph';

  // Find best lap
  const bestLap = data.laps.find(l => l.is_best) || data.laps[0];
  selectedLap = bestLap ? bestLap.global_lap : 1;

  // Populate lap selects
  ['speed-lap-select', 'gforce-lap-select', 'rotation-lap-select'].forEach(id => {
    const el = document.getElementById(id);
    if (el) populateLapSelect(el, data.laps, selectedLap);
  });

  // Draw all charts
  drawLapTimesChart(data.laps);
  drawLapProgressionChart(data.laps);
  await Promise.all([
    loadSpeedTrace(selectedLap),
    loadTrackMap(selectedLap),
    loadGGDiagram(),
    loadZonePie(),
    loadSpeedHistogram(),
    loadBestLapBreakdown(),
    loadAccelerationTraces(selectedLap),
    loadRotationTraces(selectedLap),
    loadBattery(),
  ]);
}

// ── Lap time bar chart ──
function drawLapTimesChart(laps) {
  // Filter out extreme outlier laps (>3× the median) for display purposes
  const allTimes = laps.map(l => l.lap_time).filter(t => t > 0).sort((a, b) => a - b);
  const median = allTimes[Math.floor(allTimes.length / 2)] || 60;
  const displayMax = median * 2.5; // cap y-axis at 2.5× median

  const colors = laps.map(l => {
    if (l.is_best) return '#00d4aa';
    if (l.lap_time > displayMax) return '#333'; // dim extreme outliers
    return '#444';
  });
  const times = laps.map(l => l.lap_time);
  const labels = laps.map(l => `Lap ${l.global_lap}`);
  const texts = laps.map(l => fmtLap(l.lap_time));

  const trace = {
    x: labels, y: times, type: 'bar',
    marker: { color: colors },
    text: texts, textposition: 'outside',
    hovertemplate: 'Lap %{x}<br>%{text}<extra></extra>',
    textfont: { size: 9 },
  };

  plotChart('lap-times-chart', [trace], {
    yaxis: { title: 'Lap Time (s)', gridcolor: GRID_COLOR, range: [0, displayMax] },
    xaxis: { gridcolor: GRID_COLOR },
    margin: { t: 25, l: 55, r: 10, b: 35 },
    bargap: 0.3,
  });

  // Click bar → select lap
  document.getElementById('lap-times-chart').on('plotly_click', d => {
    const lapIdx = d.points[0].pointIndex;
    selectedLap = laps[lapIdx].global_lap;
    refreshForLap(selectedLap);
  });
}

// ── Lap progression ──
function drawLapProgressionChart(laps) {
  // Exclude outlier laps from progression chart (>3× median)
  const allTimes = laps.map(l => l.lap_time).filter(t => t > 0).sort((a, b) => a - b);
  const median = allTimes[Math.floor(allTimes.length / 2)] || 60;
  const displayMax = median * 2.5;
  const filteredLaps = laps.filter(l => l.lap_time <= displayMax);

  const x = filteredLaps.map(l => l.global_lap);
  const y = filteredLaps.map(l => l.lap_time);
  const colors = filteredLaps.map(l => l.is_best ? '#00d4aa' : '#888');

  const trace = {
    x, y, type: 'scatter', mode: 'lines+markers',
    line: { color: '#555', width: 1.5 },
    marker: { color: colors, size: 7 },
    text: filteredLaps.map(l => fmtLap(l.lap_time)),
    hovertemplate: 'Lap %{x}: %{text}<extra></extra>',
  };

  plotChart('lap-progression-chart', [trace], {
    yaxis: { title: 'Lap Time (s)', gridcolor: GRID_COLOR, autorange: 'reversed' },
    xaxis: { title: 'Lap Number', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
    annotations: [{ xref: 'paper', yref: 'paper', x: 0.01, y: 0.98,
      text: 'Lower = faster', showarrow: false,
      font: { color: '#555', size: 10 } }],
  });
}

// ── Lap chart tabs ──
document.querySelectorAll('#lapChartTabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#lapChartTabs button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('lap-times-chart').classList.toggle('d-none', btn.dataset.target !== 'lap-times-chart');
    document.getElementById('lap-progression-chart').classList.toggle('d-none', btn.dataset.target !== 'lap-progression-chart');
    Plotly.Plots.resize(btn.dataset.target);
  });
});

// ── Speed trace ──
async function loadSpeedTrace(lap) {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/speed_trace?lap=${lap}`);
  const x = xAxisMode === 'distance' ? data.distance_ft : data.time;
  const xTitle = xAxisMode === 'distance' ? 'Distance (ft)' : 'Time (s)';
  const lapInfo = overviewData?.laps?.find(l => l.global_lap === lap);
  const color = lapInfo?.is_best ? '#00d4aa' : '#4a90e2';

  plotChart('speed-trace-chart', [lineTrace(x, data.speed_mph, `Lap ${lap}`, color)], {
    yaxis: { title: 'Speed (mph)', gridcolor: GRID_COLOR },
    xaxis: { title: xTitle, gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
  });
}

// X-axis toggle
document.getElementById('xaxis-time')?.addEventListener('click', () => {
  xAxisMode = 'time';
  document.getElementById('xaxis-time').classList.add('active');
  document.getElementById('xaxis-dist').classList.remove('active');
  loadSpeedTrace(selectedLap);
});
document.getElementById('xaxis-dist')?.addEventListener('click', () => {
  xAxisMode = 'distance';
  document.getElementById('xaxis-dist').classList.add('active');
  document.getElementById('xaxis-time').classList.remove('active');
  loadSpeedTrace(selectedLap);
});

document.getElementById('speed-lap-select')?.addEventListener('change', e => {
  selectedLap = parseInt(e.target.value);
  loadSpeedTrace(selectedLap);
});

// ── Track map ──
async function loadTrackMap(lap) {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/track_map?lap=${lap}`);
  if (!data.x_ft.length) return;

  const trace = {
    x: data.x_ft, y: data.y_ft, type: 'scatter', mode: 'markers',
    marker: {
      color: data.speed_mph, colorscale: 'RdYlBu', reversescale: true,
      size: 4, colorbar: { title: 'mph', thickness: 10, len: 0.6, tickfont: { size: 9 } },
    },
    hovertemplate: '%{marker.color:.1f} mph<extra></extra>',
  };

  plotChart('track-map-chart', [trace], {
    xaxis: { title: 'ft (East/West)', scaleanchor: 'y', scaleratio: 1,
      gridcolor: GRID_COLOR, zeroline: false },
    yaxis: { title: 'ft (North/South)', gridcolor: GRID_COLOR, zeroline: false },
    margin: { t: 15, l: 55, r: 20, b: 40 },
  });
}

// ── G-G Diagram ──
async function loadGGDiagram() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/gg_diagram?lap=all`);
  if (!data.lateral_g.length) return;

  const trace = {
    x: data.lateral_g, y: data.inline_g, type: 'scatter', mode: 'markers',
    marker: {
      color: data.speed_mph, colorscale: 'RdYlBu', reversescale: true,
      size: 3, opacity: 0.7,
      colorbar: { title: 'mph', thickness: 8, len: 0.5, tickfont: { size: 9 } },
    },
    hovertemplate: 'Lat: %{x:.2f}g  Lon: %{y:.2f}g<extra></extra>',
  };

  // Reference circles
  const circle = (r, color) => {
    const t = Array.from({ length: 100 }, (_, i) => (2 * Math.PI * i) / 99);
    return {
      x: t.map(a => r * Math.cos(a)), y: t.map(a => r * Math.sin(a)),
      type: 'scatter', mode: 'lines',
      line: { color, width: 1, dash: 'dot' },
      hoverinfo: 'none', showlegend: false,
    };
  };

  plotChart('gg-chart', [circle(1.5, 'rgba(255,100,100,0.25)'), circle(1, 'rgba(255,255,255,0.2)'), trace], {
    xaxis: { title: 'Lateral G (← Left   Right →)', scaleanchor: 'y', scaleratio: 1,
      gridcolor: GRID_COLOR, range: [-2, 2] },
    yaxis: { title: 'Longitudinal G (↓ Braking   Accel ↑)', gridcolor: GRID_COLOR, range: [-2, 2] },
    margin: { t: 15, l: 60, r: 20, b: 45 },
    annotations: [
      { x: 0, y: 1.05, text: '1g', showarrow: false, font: { color: '#555', size: 9 } },
      { x: 0, y: 1.55, text: '1.5g', showarrow: false, font: { color: '#833', size: 9 } },
    ],
  });
}

// ── Zone Pie ──
async function loadZonePie() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/zone_pie`);
  const trace = {
    labels: ['Braking', 'Cornering', 'Acceleration', 'Coasting'],
    values: [data.braking, data.cornering, data.accelerating, data.coasting],
    type: 'pie', hole: 0.45,
    marker: { colors: ['#e74c3c', '#f39c12', '#2ecc71', '#555'] },
    textinfo: 'label+percent', textfont: { size: 10 },
    hovertemplate: '%{label}: %{value:.1f}%<extra></extra>',
  };
  plotChart('zone-pie-chart', [trace], {
    margin: { t: 10, l: 10, r: 10, b: 10 },
    showlegend: false,
  });
}

// ── Speed Histogram ──
async function loadSpeedHistogram() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/speed_histogram`);
  const trace = {
    x: data.bins, y: data.counts, type: 'bar',
    marker: { color: data.bins.map(b => {
      const maxB = Math.max(...data.bins);
      const ratio = b / maxB;
      const r = Math.round(ratio * 220);
      const g = Math.round((1 - ratio) * 180 + 80);
      return `rgb(${r},${g},50)`;
    })},
    hovertemplate: '%{x:.1f} mph: %{y} samples<extra></extra>',
  };
  plotChart('speed-histogram-chart', [trace], {
    xaxis: { title: 'Speed (mph)', gridcolor: GRID_COLOR },
    yaxis: { title: 'Samples', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
    bargap: 0.05,
  });
}

// ── Best Lap Breakdown ──
async function loadBestLapBreakdown() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/best_lap_breakdown`);
  if (!data.speed_mph.length) return;

  const speedTrace = lineTrace(data.time, data.speed_mph, 'Speed (mph)', '#00d4aa');
  speedTrace.fill = 'tozeroy';
  speedTrace.fillcolor = 'rgba(0,212,170,0.08)';

  // Zone shapes
  const shapes = (data.zones || []).map(z => ({
    type: 'rect', xref: 'x', yref: 'paper',
    x0: z.start, x1: z.end, y0: 0, y1: 1,
    fillcolor: z.color, opacity: 0.15, line: { width: 0 },
  }));

  plotChart('best-lap-breakdown-chart', [speedTrace], {
    yaxis: { title: 'Speed (mph)', gridcolor: GRID_COLOR },
    xaxis: { title: 'Time (s)', gridcolor: GRID_COLOR },
    shapes,
    margin: { t: 15, l: 55, r: 10, b: 40 },
  });
}

// ── Acceleration Traces ──
async function loadAccelerationTraces(lap) {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/acceleration_traces?lap=${lap}`);

  const zeroLine = { type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 0, y1: 0,
    line: { color: '#444', width: 1, dash: 'dot' } };

  const layoutBase = (title) => ({
    yaxis: { title, gridcolor: GRID_COLOR, zeroline: false },
    xaxis: { title: 'Time (s)', gridcolor: GRID_COLOR },
    margin: { t: 10, l: 55, r: 5, b: 40 },
    shapes: [zeroLine],
  });

  plotChart('inline-g-chart', [lineTrace(data.time, data.inline_g, 'Longitudinal G', '#e74c3c')], layoutBase('G-Force'));
  plotChart('lateral-g-chart', [lineTrace(data.time, data.lateral_g, 'Lateral G', '#f39c12')], layoutBase('G-Force'));
  plotChart('vertical-g-chart', [lineTrace(data.time, data.vertical_g, 'Vertical G', '#9b59b6')], layoutBase('G-Force'));
}

document.getElementById('gforce-lap-select')?.addEventListener('change', e => {
  loadAccelerationTraces(parseInt(e.target.value));
});

// ── Rotation Traces ──
async function loadRotationTraces(lap) {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/rotation_traces?lap=${lap}`);

  const layoutBase = (title) => ({
    yaxis: { title, gridcolor: GRID_COLOR },
    xaxis: { title: 'Time (s)', gridcolor: GRID_COLOR },
    margin: { t: 10, l: 60, r: 5, b: 40 },
  });

  plotChart('yaw-chart', [lineTrace(data.time, data.yaw_rate, 'Yaw Rate', '#3498db')], layoutBase('deg/s'));
  plotChart('roll-chart', [lineTrace(data.time, data.roll_rate, 'Roll Rate', '#1abc9c')], layoutBase('deg/s'));
  plotChart('pitch-chart', [lineTrace(data.time, data.pitch_rate, 'Pitch Rate', '#e67e22')], layoutBase('deg/s'));
}

document.getElementById('rotation-lap-select')?.addEventListener('change', e => {
  loadRotationTraces(parseInt(e.target.value));
});

// ── Battery ──
async function loadBattery() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/battery`);
  if (!data.time.length) return;
  plotChart('battery-chart', [lineTrace(data.time, data.voltage, 'Logger Battery (V)', '#888')], {
    yaxis: { title: 'Volts', gridcolor: GRID_COLOR, rangemode: 'tozero' },
    xaxis: { title: 'Time (s)', gridcolor: GRID_COLOR },
    margin: { t: 10, l: 50, r: 10, b: 35 },
  });
}

// ── Refresh selected lap for traces ──
function refreshForLap(lap) {
  selectedLap = lap;
  ['speed-lap-select', 'gforce-lap-select', 'rotation-lap-select'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = lap;
  });
  loadSpeedTrace(lap);
  loadAccelerationTraces(lap);
  loadRotationTraces(lap);
  loadTrackMap(lap);
}

// ── Upload recording (dashboard nav button) ──
document.getElementById('nav-upload-btn')?.addEventListener('click', () => {
  document.getElementById('upload-result')?.classList.add('d-none');
  document.getElementById('upload-error')?.classList.add('d-none');
  document.getElementById('upload-progress')?.classList.add('d-none');
  new bootstrap.Modal(document.getElementById('uploadModal')).show();
});

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('upload-file-input');
dropZone?.addEventListener('click', () => fileInput?.click());
dropZone?.addEventListener('dragover', e => { e.preventDefault(); dropZone.style.borderColor = '#00d4aa'; });
dropZone?.addEventListener('dragleave', () => { dropZone.style.borderColor = ''; });
dropZone?.addEventListener('drop', e => {
  e.preventDefault(); dropZone.style.borderColor = '';
  if (e.dataTransfer.files[0]) dashboardUpload(e.dataTransfer.files[0]);
});
fileInput?.addEventListener('change', () => { if (fileInput.files[0]) dashboardUpload(fileInput.files[0]); });

async function dashboardUpload(file) {
  document.getElementById('upload-progress')?.classList.remove('d-none');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch(`/api/sessions/${SESSION_ID}/upload`, { method: 'POST', body: fd });
    const data = await r.json();
    document.getElementById('upload-progress')?.classList.add('d-none');
    if (!r.ok) throw new Error(data.error);
    const res = document.getElementById('upload-result');
    if (res) { res.textContent = `✓ Uploaded "${data.recording_name}" — refreshing…`; res.classList.remove('d-none'); }
    setTimeout(() => window.location.reload(), 1500);
  } catch (e) {
    document.getElementById('upload-progress')?.classList.add('d-none');
    const err = document.getElementById('upload-error');
    if (err) { err.textContent = 'Upload failed: ' + e.message; err.classList.remove('d-none'); }
  }
}

// ── Init ──
loadOverview().catch(console.error);
