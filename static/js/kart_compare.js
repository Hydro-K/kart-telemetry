/* Kart head-to-head comparison */

async function loadKartCompare() {
  const data = await apiFetch('/api/karts/compare');
  const k1 = data.kart_1;
  const k2 = data.kart_2;

  // ── Stat Cards ──
  const grid = document.getElementById('kart-stat-cards');
  grid.innerHTML = `
    ${statCard(k1, 1)}
    ${statCard(k2, 2)}
  `;

  // ── Lap time history ──
  drawLapHistory(k1, k2);

  // ── G-G diagrams ──
  await loadGG(k1, 'gg-kart1', k1.color || TEAL);
  await loadGG(k2, 'gg-kart2', k2.color || ORANGE);

  // ── Speed comparison ──
  await drawSpeedComparison(k1, k2);

  // ── Track maps ──
  await loadTrackMap(k1, 'trackmap-kart1', k1.color || TEAL);
  await loadTrackMap(k2, 'trackmap-kart2', k2.color || ORANGE);
}

function statCard(k, num) {
  const s = k.stats || {};
  const color = k.color || '#888';
  const best = s.best_lap != null ? fmtLap(s.best_lap) : '--:--';
  const avg = s.avg_lap != null ? fmtLap(s.avg_lap) : '--:--';
  const topSpd = s.max_speed != null ? `${s.max_speed.toFixed(1)} mph` : '-- mph';
  const totalLaps = s.total_laps || 0;
  const sessions = s.session_count || 0;

  return `
  <div class="col-md-6">
    <div class="card h-100" style="border-color:${color}!important;border-width:2px!important">
      <div class="card-header border-0 pb-0" style="background:transparent">
        <div class="d-flex align-items-center gap-2 mb-2">
          <span style="width:14px;height:14px;border-radius:50%;background:${color};display:inline-block"></span>
          <h5 class="mb-0 fw-bold">${k.name}</h5>
          <span class="badge bg-secondary ms-auto">${sessions} session${sessions !== 1 ? 's' : ''}</span>
        </div>
      </div>
      <div class="card-body pt-2">
        <div class="row g-3 text-center">
          <div class="col-3">
            <div class="fw-bold" style="color:${color};font-size:1.3rem;font-variant-numeric:tabular-nums">${best}</div>
            <div style="font-size:.6rem;letter-spacing:.1em;color:#888">BEST LAP</div>
          </div>
          <div class="col-3">
            <div class="fw-bold" style="font-size:1.3rem;font-variant-numeric:tabular-nums">${avg}</div>
            <div style="font-size:.6rem;letter-spacing:.1em;color:#888">AVG LAP</div>
          </div>
          <div class="col-3">
            <div class="fw-bold" style="font-size:1.3rem">${topSpd}</div>
            <div style="font-size:.6rem;letter-spacing:.1em;color:#888">TOP SPEED</div>
          </div>
          <div class="col-3">
            <div class="fw-bold" style="font-size:1.3rem">${totalLaps}</div>
            <div style="font-size:.6rem;letter-spacing:.1em;color:#888">TOTAL LAPS</div>
          </div>
        </div>
        ${k.best_lap_detail ? `
        <div class="mt-3 p-2 rounded" style="background:#0d0d0d;font-size:.8rem">
          <span class="text-secondary">Best in: </span>${k.best_lap_detail.session_name}
          ${k.best_lap_detail.max_speed ? `<span class="ms-3 text-secondary">Max: </span>${k.best_lap_detail.max_speed.toFixed(1)} mph` : ''}
          ${k.best_lap_detail.max_lat_g ? `<span class="ms-3 text-secondary">Lat G: </span>${k.best_lap_detail.max_lat_g.toFixed(2)}g` : ''}
        </div>` : ''}
      </div>
    </div>
  </div>`;
}

function drawLapHistory(k1, k2) {
  const traces = [];
  if (k1.lap_history?.length) {
    traces.push({
      x: k1.lap_history.map((_, i) => i + 1),
      y: k1.lap_history.map(l => l.lap_time),
      name: k1.name, type: 'bar',
      marker: { color: k1.color || TEAL, opacity: 0.8 },
      hovertemplate: `${k1.name} Lap %{x}: %{customdata}<extra></extra>`,
      customdata: k1.lap_history.map(l => fmtLap(l.lap_time)),
    });
  }
  if (k2.lap_history?.length) {
    const offset = (k1.lap_history?.length || 0);
    traces.push({
      x: k2.lap_history.map((_, i) => i + 1 + offset),
      y: k2.lap_history.map(l => l.lap_time),
      name: k2.name, type: 'bar',
      marker: { color: k2.color || ORANGE, opacity: 0.8 },
      hovertemplate: `${k2.name} Lap %{x}: %{customdata}<extra></extra>`,
      customdata: k2.lap_history.map(l => fmtLap(l.lap_time)),
    });
  }
  if (!traces.length) return;

  Plotly.react('compare-laptimes-chart', traces, basePlotLayout({
    yaxis: { title: 'Lap Time (s)', gridcolor: GRID_COLOR },
    xaxis: { title: 'Lap Number', gridcolor: GRID_COLOR },
    barmode: 'overlay', bargap: 0.2,
    margin: { t: 20, l: 55, r: 10, b: 40 },
  }), PLOT_CONFIG);
}

async function loadGG(kart, divId, color) {
  // Get best session for this kart
  const sessions = await apiFetch(`/api/karts/${kart.id}/sessions`);
  const best = sessions.find(s => s.best_lap_time != null);
  if (!best) { document.getElementById(divId).innerHTML = '<div class="text-secondary text-center pt-4 small">No session data</div>'; return; }

  const data = await apiFetch(`/api/analysis/${best.id}/gg_diagram?lap=all`);
  if (!data.lateral_g.length) return;

  const circleTrace = (r, c) => {
    const t = Array.from({ length: 100 }, (_, i) => (2 * Math.PI * i) / 99);
    return { x: t.map(a => r * Math.cos(a)), y: t.map(a => r * Math.sin(a)),
      type: 'scatter', mode: 'lines', line: { color: c, width: 1, dash: 'dot' },
      hoverinfo: 'none', showlegend: false };
  };

  Plotly.react(divId, [
    circleTrace(1.5, 'rgba(255,100,100,0.2)'),
    circleTrace(1, 'rgba(255,255,255,0.15)'),
    { x: data.lateral_g, y: data.inline_g, type: 'scatter', mode: 'markers',
      marker: { size: 2, color, opacity: 0.5 }, showlegend: false,
      hovertemplate: 'Lat: %{x:.2f}g  Lon: %{y:.2f}g<extra></extra>' },
  ], basePlotLayout({
    xaxis: { title: 'Lateral G', range: [-2, 2], scaleanchor: 'y', scaleratio: 1, gridcolor: GRID_COLOR },
    yaxis: { title: 'Longitudinal G', range: [-2, 2], gridcolor: GRID_COLOR },
    margin: { t: 10, l: 55, r: 10, b: 40 },
  }), PLOT_CONFIG);
}

async function drawSpeedComparison(k1, k2) {
  const sess1 = (await apiFetch(`/api/karts/${k1.id}/sessions`)).find(s => s.best_lap_time != null);
  const sess2 = (await apiFetch(`/api/karts/${k2.id}/sessions`)).find(s => s.best_lap_time != null);
  const traces = [];

  if (sess1) {
    try {
      const d1 = await apiFetch(`/api/analysis/${sess1.id}/speed_trace`);
      traces.push({ x: d1.distance_ft, y: d1.speed_mph, name: k1.name,
        type: 'scatter', mode: 'lines', line: { color: k1.color || TEAL, width: 2 } });
    } catch {}
  }
  if (sess2) {
    try {
      const d2 = await apiFetch(`/api/analysis/${sess2.id}/speed_trace`);
      traces.push({ x: d2.distance_ft, y: d2.speed_mph, name: k2.name,
        type: 'scatter', mode: 'lines', line: { color: k2.color || ORANGE, width: 2, dash: 'dash' } });
    } catch {}
  }
  if (!traces.length) return;

  Plotly.react('compare-speed-chart', traces, basePlotLayout({
    yaxis: { title: 'Speed (mph)', gridcolor: GRID_COLOR },
    xaxis: { title: 'Distance (ft)', gridcolor: GRID_COLOR },
    margin: { t: 20, l: 55, r: 10, b: 40 },
  }), PLOT_CONFIG);
}

async function loadTrackMap(kart, divId, color) {
  const sessions = await apiFetch(`/api/karts/${kart.id}/sessions`);
  const best = sessions.find(s => s.best_lap_time != null);
  if (!best) return;
  try {
    const data = await apiFetch(`/api/analysis/${best.id}/track_map`);
    if (!data.x_ft.length) return;
    Plotly.react(divId, [{
      x: data.x_ft, y: data.y_ft, type: 'scatter', mode: 'markers',
      marker: { color, size: 3, opacity: 0.7 },
    }], basePlotLayout({
      xaxis: { scaleanchor: 'y', scaleratio: 1, gridcolor: GRID_COLOR,
        zeroline: false, showticklabels: false },
      yaxis: { gridcolor: GRID_COLOR, zeroline: false, showticklabels: false },
      margin: { t: 5, l: 5, r: 5, b: 5 },
    }), PLOT_CONFIG);
  } catch {}
}

// ── AI insight ──
document.getElementById('ai-generate-btn')?.addEventListener('click', async () => {
  const thinking = document.getElementById('ai-insight-thinking');
  const content = document.getElementById('ai-insight-content');
  const placeholder = document.getElementById('ai-insight-placeholder');
  thinking.classList.remove('d-none');
  placeholder.classList.add('d-none');
  content.classList.add('d-none');
  content.textContent = '';

  try {
    const es = new EventSource('/api/ai/chat');
    // Use fetch + SSE for POST
    const response = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: null,
        message: 'Compare Kart 1 and Kart 2 based on all available data. What are the key differences in performance, driver input, and handling? What specific changes would make each kart faster?',
        stream: false,
      }),
    });
    const data = await response.json();
    thinking.classList.add('d-none');
    if (data.error) { content.textContent = 'Error: ' + data.error; }
    else { content.textContent = data.reply; }
    content.classList.remove('d-none');
  } catch (e) {
    thinking.classList.add('d-none');
    content.textContent = 'Error: ' + e.message;
    content.classList.remove('d-none');
  }
});

// ── Init ──
loadKartCompare().catch(console.error);
