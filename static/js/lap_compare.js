/* Lap comparison page */

const SESSION_ID = parseInt(document.getElementById('session-id').dataset.id);

async function initLapCompare() {
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/overview`);
  const laps = data.laps;
  if (laps.length < 2) {
    document.body.innerHTML += '<div class="alert alert-warning m-4">Need at least 2 laps to compare.</div>';
    return;
  }

  const lap1Select = document.getElementById('lap1-select');
  const lap2Select = document.getElementById('lap2-select');
  const bestLap = laps.find(l => l.is_best) || laps[0];
  const secondLap = laps.find(l => !l.is_best) || laps[1];

  populateLapSelect(lap1Select, laps, bestLap.global_lap);
  populateLapSelect(lap2Select, laps, secondLap.global_lap);

  await runComparison(bestLap.global_lap, secondLap.global_lap, laps);
}

document.getElementById('compare-btn')?.addEventListener('click', async () => {
  const lap1 = parseInt(document.getElementById('lap1-select').value);
  const lap2 = parseInt(document.getElementById('lap2-select').value);
  if (lap1 === lap2) { alert('Please select two different laps.'); return; }
  const data = await apiFetch(`/api/analysis/${SESSION_ID}/overview`);
  await runComparison(lap1, lap2, data.laps);
});

async function runComparison(lap1, lap2, allLaps) {
  const l1 = allLaps.find(l => l.global_lap === lap1);
  const l2 = allLaps.find(l => l.global_lap === lap2);

  // Update header times
  document.getElementById('lap1-time').textContent = l1 ? fmtLap(l1.lap_time) : '--:--';
  document.getElementById('lap2-time').textContent = l2 ? fmtLap(l2.lap_time) : '--:--';

  const data = await apiFetch(`/api/analysis/${SESSION_ID}/lap_compare?lap1=${lap1}&lap2=${lap2}`);

  // ── Speed overlay ──
  Plotly.react('compare-speed-chart', [
    { x: data.distance_ft, y: data.lap1_speed_mph, name: `Lap ${lap1}`,
      type: 'scatter', mode: 'lines', line: { color: TEAL, width: 2 } },
    { x: data.distance_ft, y: data.lap2_speed_mph, name: `Lap ${lap2}`,
      type: 'scatter', mode: 'lines', line: { color: ORANGE, width: 2, dash: 'dash' } },
  ], basePlotLayout({
    yaxis: { title: 'Speed (mph)', gridcolor: GRID_COLOR },
    xaxis: { title: 'Distance (ft)', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
  }), PLOT_CONFIG);

  // ── Delta time ──
  const deltaColors = data.delta_time.map(d => d >= 0 ? TEAL : ORANGE);
  Plotly.react('compare-delta-chart', [{
    x: data.distance_ft, y: data.delta_time, type: 'scatter', mode: 'lines',
    fill: 'tozeroy',
    line: { color: '#888', width: 1.5 },
    fillcolor: 'rgba(0,212,170,0.15)',
    hovertemplate: '%{x:.0f} ft: %{y:.3f}s<extra></extra>',
  }, {
    x: data.distance_ft.filter((_, i) => data.delta_time[i] < 0),
    y: data.delta_time.filter(d => d < 0),
    type: 'bar', marker: { color: 'rgba(255,107,53,0.35)' },
    showlegend: false, hoverinfo: 'skip',
  }], basePlotLayout({
    yaxis: { title: 'Delta (s)', gridcolor: GRID_COLOR, zeroline: true, zerolinecolor: '#555' },
    xaxis: { title: 'Distance (ft)', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
    annotations: [
      { xref: 'paper', yref: 'paper', x: 0.01, y: 0.95, showarrow: false,
        text: `← Lap ${lap1} faster`, font: { color: TEAL, size: 10 } },
      { xref: 'paper', yref: 'paper', x: 0.01, y: 0.05, showarrow: false,
        text: `← Lap ${lap2} faster`, font: { color: ORANGE, size: 10 } },
    ],
  }), PLOT_CONFIG);

  // ── Inline G overlay ──
  Plotly.react('compare-inlineg-chart', [
    { x: data.distance_ft, y: data.lap1_inline_g, name: `Lap ${lap1}`,
      type: 'scatter', mode: 'lines', line: { color: TEAL, width: 1.5 } },
    { x: data.distance_ft, y: data.lap2_inline_g, name: `Lap ${lap2}`,
      type: 'scatter', mode: 'lines', line: { color: ORANGE, width: 1.5, dash: 'dash' } },
  ], basePlotLayout({
    yaxis: { title: 'Longitudinal G', gridcolor: GRID_COLOR, zeroline: true, zerolinecolor: '#444' },
    xaxis: { title: 'Distance (ft)', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
  }), PLOT_CONFIG);

  // ── Track maps ──
  const tm1 = await apiFetch(`/api/analysis/${SESSION_ID}/track_map?lap=${lap1}`);
  const tm2 = await apiFetch(`/api/analysis/${SESSION_ID}/track_map?lap=${lap2}`);

  document.getElementById('trackmap-lap1-label').textContent = `Lap ${lap1} Track Map`;
  document.getElementById('trackmap-lap2-label').textContent = `Lap ${lap2} Track Map`;

  const tmLayout = basePlotLayout({
    xaxis: { scaleanchor: 'y', scaleratio: 1, gridcolor: GRID_COLOR,
      zeroline: false, showticklabels: false },
    yaxis: { gridcolor: GRID_COLOR, zeroline: false, showticklabels: false },
    margin: { t: 5, l: 5, r: 5, b: 5 },
  });

  Plotly.react('compare-trackmap-lap1', [{
    x: tm1.x_ft, y: tm1.y_ft, type: 'scatter', mode: 'markers',
    marker: { color: tm1.speed_mph, colorscale: 'RdYlBu', reversescale: true, size: 4 },
  }], tmLayout, PLOT_CONFIG);

  Plotly.react('compare-trackmap-lap2', [{
    x: tm2.x_ft, y: tm2.y_ft, type: 'scatter', mode: 'markers',
    marker: { color: tm2.speed_mph, colorscale: 'RdYlBu', reversescale: true, size: 4 },
  }], tmLayout, PLOT_CONFIG);
}

initLapCompare().catch(console.error);
