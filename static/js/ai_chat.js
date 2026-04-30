/* AI race engineer chat interface */

const SESSION_ID = parseInt(document.getElementById('session-id').dataset.id);
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('chat-send');

// ── Check AI status on load ──
(async function checkStatus() {
  const pill = document.getElementById('ai-status-pill');
  const banner = document.getElementById('ai-offline-banner');
  try {
    const s = await apiFetch('/api/ai/status');
    if (s.online && s.model_ready) {
      pill.textContent = '● Online';
      pill.className = 'ms-auto badge bg-success';
      banner.classList.add('d-none');
    } else if (s.online) {
      pill.textContent = `Loading ${s.model}…`;
      pill.className = 'ms-auto badge bg-warning text-dark';
      banner.classList.add('d-none');
    } else {
      pill.textContent = '● Offline';
      pill.className = 'ms-auto badge bg-danger';
      banner.classList.remove('d-none');
    }
  } catch {
    pill.textContent = '● Offline';
    pill.className = 'ms-auto badge bg-danger';
    banner.classList.remove('d-none');
  }
})();

// ── Load session context panel ──
(async function loadContextPanel() {
  const panel = document.getElementById('session-context-panel');
  try {
    const data = await apiFetch(`/api/analysis/${SESSION_ID}/overview`);
    panel.innerHTML = `
      <div class="mb-3">
        <div class="small text-secondary mb-1">SESSION</div>
        <div class="fw-semibold">${data.name}</div>
      </div>
      <div class="mb-3">
        <div class="small text-secondary mb-1">BEST LAP</div>
        <div class="fw-bold" style="color:#00d4aa;font-size:1.1rem">${data.best_lap_formatted}</div>
      </div>
      <div class="mb-3">
        <div class="small text-secondary mb-1">AVG LAP</div>
        <div class="fw-semibold">${data.avg_lap_formatted}</div>
      </div>
      <div class="mb-3">
        <div class="small text-secondary mb-1">CONSISTENCY</div>
        <div class="fw-semibold">${data.consistency_pct != null ? data.consistency_pct.toFixed(1) + '%' : '--'}</div>
      </div>
      <div class="mb-3">
        <div class="small text-secondary mb-1">TOP SPEED</div>
        <div class="fw-semibold">${data.max_speed_mph ? data.max_speed_mph.toFixed(1) + ' mph' : '--'}</div>
      </div>
      <div>
        <div class="small text-secondary mb-1">LAPS (${data.lap_count})</div>
        ${data.laps.map(l =>
          `<div class="d-flex justify-content-between small py-1 border-bottom border-secondary">
            <span class="${l.is_best ? 'text-warning fw-bold' : 'text-secondary'}">Lap ${l.global_lap}${l.is_best ? ' ★' : ''}</span>
            <span>${fmtLap(l.lap_time)}</span>
          </div>`
        ).join('')}
      </div>
    `;
  } catch {
    panel.innerHTML = '<div class="small text-secondary p-2">Could not load session data.</div>';
  }
})();

// ── Load existing conversation ──
(async function loadHistory() {
  try {
    const msgs = await apiFetch(`/api/ai/conversations/${SESSION_ID}`);
    msgs.forEach(m => {
      if (m.role !== 'user' && m.role !== 'assistant') return;
      appendMessage(m.role, m.content, false);
    });
    scrollChat();
  } catch {}
})();

// ── Send message ──
async function sendMessage(text) {
  text = text.trim();
  if (!text) return;
  chatInput.value = '';
  appendMessage('user', text);
  const thinkingEl = appendThinking();
  sendBtn.disabled = true;

  try {
    const response = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: SESSION_ID, message: text, stream: true }),
    });

    if (!response.ok) throw new Error('Server error');

    // Remove thinking bubble, add streaming assistant bubble
    thinkingEl.remove();
    const msgEl = appendMessage('assistant', '', true);
    const bubble = msgEl.querySelector('.chat-bubble');
    let fullText = '';

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const chunk = JSON.parse(line.slice(6));
          if (chunk.error) {
            bubble.textContent = '⚠ ' + chunk.error;
            break;
          }
          if (chunk.token) {
            fullText += chunk.token;
            bubble.textContent = fullText;
            scrollChat();
          }
        } catch {}
      }
    }
  } catch (e) {
    thinkingEl.remove();
    appendMessage('assistant', '⚠ Error: ' + e.message);
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

function appendMessage(role, text, streaming = false) {
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  const label = role === 'assistant'
    ? '<strong class="text-warning d-block mb-1" style="font-size:.8rem"><i class="bi bi-robot me-1"></i>Race Engineer</strong>'
    : '';
  div.innerHTML = `
    <div class="chat-bubble">${label}<span class="msg-text">${escapeHtml(text)}</span></div>
    <div class="chat-time text-secondary" style="font-size:.7rem;margin-top:.25rem">${new Date().toLocaleTimeString()}</div>
  `;
  // For streaming, return the element so we can update it
  const bubble = div.querySelector('.msg-text');
  if (streaming) {
    // Allow raw text update without escaping during stream
    bubble.className = 'msg-text streaming';
    Object.defineProperty(bubble, 'textContent', {
      set(v) { bubble.innerText = v; },
      get() { return bubble.innerText; },
    });
  }
  chatHistory.appendChild(div);
  scrollChat();
  return div;
}

function appendThinking() {
  const div = document.createElement('div');
  div.className = 'chat-msg assistant';
  div.innerHTML = `
    <div class="chat-bubble">
      <strong class="text-warning d-block mb-1" style="font-size:.8rem"><i class="bi bi-robot me-1"></i>Race Engineer</strong>
      <span class="typing-dots"><span></span><span></span><span></span></span>
      <span class="text-secondary small ms-2">Reviewing the data…</span>
    </div>`;
  chatHistory.appendChild(div);
  scrollChat();
  return div;
}

function scrollChat() {
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function escapeHtml(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>');
}

// ── Event listeners ──
sendBtn.addEventListener('click', () => sendMessage(chatInput.value));
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(chatInput.value); }
});

document.querySelectorAll('.quick-q').forEach(btn => {
  btn.addEventListener('click', () => sendMessage(btn.dataset.q));
});

document.getElementById('clear-chat')?.addEventListener('click', async () => {
  if (!confirm('Clear conversation history?')) return;
  await fetch(`/api/ai/conversations/${SESSION_ID}`, { method: 'DELETE' });
  // Keep only the intro message
  const msgs = chatHistory.querySelectorAll('.chat-msg');
  msgs.forEach((m, i) => { if (i > 0) m.remove(); });
});
