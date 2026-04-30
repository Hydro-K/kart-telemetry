/* Sessions home page */

let allSessions = [];
let allKarts = [];
let currentUploadSessionId = null;

async function loadKarts() {
  try {
    allKarts = await apiFetch('/api/karts');
    // Build kart filter tabs
    const filter = document.getElementById('kartFilter');
    // Remove any previously injected kart buttons (keep "All Karts")
    filter.querySelectorAll('[data-kart]:not([data-kart="all"])').forEach(b => b.parentElement.remove());
    allKarts.forEach(k => {
      const li = document.createElement('li');
      li.className = 'nav-item';
      li.innerHTML = `<button class="nav-link" data-kart="${k.id}" style="color:${k.color}">
        <span class="me-1" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${k.color}"></span>${k.name}
      </button>`;
      filter.appendChild(li);
      li.querySelector('button').addEventListener('click', handleKartFilter);
    });
  } catch { /* keep static fallback */ }
}

async function loadSessions() {
  const grid = document.getElementById('sessions-grid');
  try {
    allSessions = await apiFetch('/api/sessions');
    renderSessions(allSessions);
  } catch (e) {
    grid.innerHTML = `<div class="col-12 text-center text-danger py-4"><i class="bi bi-exclamation-triangle me-2"></i>${e.message}</div>`;
  }
}

function renderSessions(sessions) {
  const grid = document.getElementById('sessions-grid');
  const tpl = document.getElementById('session-card-tpl');

  if (sessions.length === 0) {
    grid.innerHTML = `
      <div class="col-12 text-center py-5 text-secondary">
        <i class="bi bi-folder2-open fs-1 d-block mb-3"></i>
        <h6>No sessions yet</h6>
        <p class="small">Create a session, then upload AiM recording files to get started.</p>
        <button class="btn btn-success" data-bs-toggle="modal" data-bs-target="#newSessionModal">
          <i class="bi bi-plus-circle me-2"></i>Create First Session
        </button>
      </div>`;
    return;
  }

  grid.innerHTML = '';
  sessions.forEach(s => {
    const clone = tpl.content.cloneNode(true);
    const card = clone.querySelector('.session-card');

    // Kart color / name
    const color = s.kart_color || '#888';
    clone.querySelector('.kart-dot').style.background = color;
    clone.querySelector('.kart-name').textContent = s.kart_name || 'Unknown Kart';

    // Session name + date
    clone.querySelector('.session-name').textContent = s.name;
    clone.querySelector('.session-date').textContent = s.event_date || formatDate(s.created_at);

    // Stats
    clone.querySelector('.best-lap').textContent = fmtLap(s.best_lap_time);
    clone.querySelector('.avg-lap').textContent = fmtLap(s.avg_lap_time);
    clone.querySelector('.lap-count').textContent = s.lap_count || 0;
    clone.querySelector('.max-speed').textContent = s.max_speed_mph ? `${s.max_speed_mph.toFixed(1)}` : '--';

    // Consistency bar
    const pct = s.consistency_pct || 0;
    clone.querySelector('.consistency-bar').style.width = pct + '%';
    clone.querySelector('.consistency-label').textContent = `Consistency: ${pct.toFixed(1)}%`;

    // Recordings list + drivers
    const recList = clone.querySelector('.recordings-list');
    if (s.lap_count > 0) {
      const driverBadges = (s.drivers || []).map(d =>
        `<span class="badge bg-secondary me-1" style="font-size:.65rem">${d}</span>`
      ).join('');
      recList.innerHTML = `<div class="small text-secondary"><i class="bi bi-file-earmark-zip me-1"></i>${s.lap_count} lap${s.lap_count !== 1 ? 's' : ''} &nbsp;${driverBadges}</div>`;
    }

    // Card kart border color
    card.style.borderLeftColor = color;
    card.style.borderLeftWidth = '3px';

    // Click card → go to dashboard
    card.addEventListener('click', () => window.location.href = `/dashboard/${s.id}`);

    // Analyze button
    clone.querySelector('.analyze-btn').href = `/dashboard/${s.id}`;

    // Upload button (both locations)
    const uploadHandler = (e) => { e.stopPropagation(); openUploadModal(s.id); };
    clone.querySelector('.upload-btn').addEventListener('click', uploadHandler);
    clone.querySelector('.upload-btn2').addEventListener('click', uploadHandler);

    // Replay
    clone.querySelector('.replay-btn').href = `/replay/${s.id}`;
    clone.querySelector('.replay-btn').addEventListener('click', e => { e.stopPropagation(); window.location.href = `/replay/${s.id}`; });

    // AI
    clone.querySelector('.ai-btn').href = `/ai/${s.id}`;
    clone.querySelector('.ai-btn').addEventListener('click', e => { e.stopPropagation(); window.location.href = `/ai/${s.id}`; });

    // Delete
    clone.querySelector('.delete-btn').addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete session "${s.name}"? This cannot be undone.`)) return;
      await fetch(`/api/sessions/${s.id}`, { method: 'DELETE' });
      loadSessions();
    });

    grid.appendChild(clone);
  });
}

function formatDate(dtStr) {
  if (!dtStr) return '';
  try {
    return new Date(dtStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return ''; }
}

// ── Kart filter ──
function handleKartFilter(e) {
  const btn = e.currentTarget;
  document.querySelectorAll('#kartFilter button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const kart = btn.dataset.kart;
  if (kart === 'all') renderSessions(allSessions);
  else renderSessions(allSessions.filter(s => String(s.kart_id) === kart));
}

// Wire up the static "All Karts" button
document.querySelector('#kartFilter button[data-kart="all"]')?.addEventListener('click', handleKartFilter);

// ── Upload modal ──
function openUploadModal(sessionId) {
  currentUploadSessionId = sessionId;
  document.getElementById('upload-result').classList.add('d-none');
  document.getElementById('upload-error').classList.add('d-none');
  document.getElementById('upload-progress').classList.add('d-none');
  // Clear driver selection
  document.querySelectorAll('input[name="upload-driver"]').forEach(r => r.checked = false);
  // Reset file input
  const fi = document.getElementById('upload-file-input');
  if (fi) fi.value = '';
  new bootstrap.Modal(document.getElementById('uploadModal')).show();
}

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('upload-file-input');

dropZone?.addEventListener('click', () => fileInput.click());
dropZone?.addEventListener('dragover', e => { e.preventDefault(); dropZone.style.borderColor = '#00d4aa'; });
dropZone?.addEventListener('dragleave', () => { dropZone.style.borderColor = ''; });
dropZone?.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.style.borderColor = '';
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});
fileInput?.addEventListener('change', () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
  if (!currentUploadSessionId) return;

  // Require driver selection
  const driverRadio = document.querySelector('input[name="upload-driver"]:checked');
  if (!driverRadio) {
    document.getElementById('upload-error').textContent = 'Please select a driver before uploading.';
    document.getElementById('upload-error').classList.remove('d-none');
    return;
  }
  const driver = driverRadio.value;

  document.getElementById('upload-progress').classList.remove('d-none');
  document.getElementById('upload-result').classList.add('d-none');
  document.getElementById('upload-error').classList.add('d-none');

  const fd = new FormData();
  fd.append('file', file);
  fd.append('driver', driver);

  try {
    const r = await fetch(`/api/sessions/${currentUploadSessionId}/upload`, { method: 'POST', body: fd });
    const data = await r.json();
    document.getElementById('upload-progress').classList.add('d-none');
    if (!r.ok) throw new Error(data.error);
    const drvStr = data.driver ? ` (${data.driver})` : '';
    const res = document.getElementById('upload-result');
    res.textContent = `✓ Uploaded "${data.recording_name}"${drvStr} — ${data.session.lap_count} total laps now in session.`;
    res.classList.remove('d-none');
    loadSessions();
  } catch (e) {
    document.getElementById('upload-progress').classList.add('d-none');
    const err = document.getElementById('upload-error');
    err.textContent = 'Upload failed: ' + e.message;
    err.classList.remove('d-none');
  }
}

// Init
loadKarts();
loadSessions();
