/* Shared utilities and AI status check */

const PLOT_BG = '#0a0a0a';
const PAPER_BG = '#111111';
const FONT_COLOR = '#cccccc';
const GRID_COLOR = '#1e1e1e';
const TEAL = '#00d4aa';
const ORANGE = '#ff6b35';

/** Base Plotly layout applied to every chart */
function basePlotLayout(overrides = {}) {
  return Object.assign({
    paper_bgcolor: PAPER_BG,
    plot_bgcolor: PLOT_BG,
    font: { color: FONT_COLOR, size: 11 },
    margin: { t: 20, l: 50, r: 20, b: 40 },
    xaxis: { gridcolor: GRID_COLOR, zerolinecolor: GRID_COLOR },
    yaxis: { gridcolor: GRID_COLOR, zerolinecolor: GRID_COLOR },
    legend: { bgcolor: 'transparent', font: { size: 10 } },
    hovermode: 'x unified',
  }, overrides);
}

const PLOT_CONFIG = { responsive: true, displayModeBar: false };

/** Format seconds as m:ss.sss */
function fmtLap(s) {
  if (s == null || isNaN(s)) return '--:--';
  const m = Math.floor(s / 60);
  const rem = (s - m * 60).toFixed(3).padStart(6, '0');
  return `${m}:${rem}`;
}

/** Fetch wrapper with JSON parse */
async function apiFetch(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`API error ${r.status}: ${url}`);
  return r.json();
}

/** Populate a <select> with lap options */
function populateLapSelect(el, laps, defaultLap) {
  el.innerHTML = '';
  laps.forEach(l => {
    const opt = document.createElement('option');
    opt.value = l.global_lap;
    opt.textContent = `Lap ${l.global_lap}  ${fmtLap(l.lap_time)}${l.is_best ? ' ★' : ''}`;
    if (l.global_lap === defaultLap) opt.selected = true;
    el.appendChild(opt);
  });
}

// ── AI status badge ──
(async function checkAiStatus() {
  const dot = document.getElementById('ai-dot');
  const txt = document.getElementById('ai-status-text');
  const badge = document.getElementById('ai-status-badge');
  if (!badge) return;
  badge.classList.remove('d-none');
  try {
    const s = await apiFetch('/api/ai/status');
    if (s.online && s.model_ready) {
      dot.style.background = '#00d4aa';
      txt.textContent = 'AI Engineer Ready';
      txt.style.color = '#00d4aa';
    } else if (s.online) {
      dot.style.background = '#f39c12';
      txt.textContent = `Loading ${s.model}…`;
      txt.style.color = '#f39c12';
    } else {
      dot.style.background = '#e74c3c';
      txt.textContent = 'AI Offline';
      txt.style.color = '#e74c3c';
    }
  } catch {
    dot.style.background = '#555';
    txt.textContent = 'AI Engineer';
  }
})();

// ── Populate kart dropdown in New Session modal from API ──
(async function populateKartDropdown() {
  const sel = document.getElementById('ns-kart');
  if (!sel) return;
  try {
    const karts = await apiFetch('/api/karts');
    sel.innerHTML = '';
    karts.forEach(k => {
      const opt = document.createElement('option');
      opt.value = k.id;
      opt.textContent = k.name;
      sel.appendChild(opt);
    });
  } catch {
    // Fallback if API fails — leave empty
  }
})();

// ── New Session modal ──
document.getElementById('ns-create-btn')?.addEventListener('click', async () => {
  const name = document.getElementById('ns-name').value.trim();
  const kart_id = parseInt(document.getElementById('ns-kart').value);
  const event_date = document.getElementById('ns-date').value || null;
  const notes = document.getElementById('ns-notes').value;
  if (!name) { alert('Please enter a session name'); return; }
  try {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, kart_id, event_date, notes }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error);
    bootstrap.Modal.getInstance(document.getElementById('newSessionModal'))?.hide();
    window.location.href = `/dashboard/${data.id}`;
  } catch (e) {
    alert('Error creating session: ' + e.message);
  }
});
