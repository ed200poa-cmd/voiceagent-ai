'use strict';

// ── State ────────────────────────────────────────────────────────────────────
const State = { IDLE: 'idle', LISTENING: 'listening', THINKING: 'thinking', SPEAKING: 'speaking' };
let appState = State.IDLE;
let sessionId = null;
let ws = null;
let recognition = null;
let synth = window.speechSynthesis;
let ttsMode = 'browser'; // 'elevenlabs' | 'browser'
let isListening = false;
let currentAudio = null;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const micBtn       = document.getElementById('mic-btn');
const micRipple    = document.getElementById('mic-ripple');
const statusBar    = document.getElementById('status-bar');
const statusText   = document.getElementById('status-text');
const statusDot    = document.getElementById('status-dot');
const waveform     = document.getElementById('waveform');
const transcriptEl = document.getElementById('transcript-list');
const apptCard     = document.getElementById('appointment-card');
const stateEl      = document.getElementById('state-badge');
const collectedEl  = document.getElementById('collected-info');
const newCallBtn   = document.getElementById('new-call-btn');

// ── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  setupMicButton();
  setupSpeechRecognition();
});

document.getElementById('start-btn')?.addEventListener('click', async () => {
  document.getElementById('start-overlay').style.display = 'none';
  await startSession();
});

async function startSession() {
  setStatus(State.THINKING, 'Connecting…');
  try {
    const r = await fetch('/api/new-session', { method: 'POST' });
    const d = await r.json();
    sessionId = d.session_id;
    ttsMode = d.tts_mode || 'browser';
    connectWebSocket();
    appendTurn('agent', d.greeting_text);
    await speak(d.greeting_text, d.greeting_audio_base64);
    setStatus(State.IDLE, 'Ready — tap mic to speak');
    document.getElementById('header-badge').textContent = `🟢 Session ${sessionId.slice(0,6)}`;
    document.getElementById('header-badge').className = 'header-badge live';
  } catch(e) {
    setStatus(State.IDLE, 'Server offline');
    appendTurn('agent', '⚠️ Cannot connect to server. Make sure VoiceAgent is running.');
  }
}

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/voice-session`);

  ws.onopen = () => console.log('WS connected');
  ws.onmessage = async (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'agent_response') {
      await handleAgentResponse(data);
    }
  };
  ws.onclose = () => {
    console.log('WS closed');
    setTimeout(connectWebSocket, 2000);
  };
  ws.onerror = (e) => console.warn('WS error', e);
}

// ── Mic button ───────────────────────────────────────────────────────────────
function setupMicButton() {
  micBtn.addEventListener('click', toggleListening);
}

function toggleListening() {
  if (appState === State.SPEAKING) { stopSpeaking(); return; }
  if (appState === State.THINKING)  return;
  if (isListening) {
    stopListening();
  } else {
    startListening();
  }
}

function startListening() {
  if (!recognition) { alert('Speech recognition not supported. Use Chrome or Edge.'); return; }
  isListening = true;
  setStatus(State.LISTENING, 'Listening…');
  micBtn.classList.add('listening');
  micRipple.classList.add('animate');
  waveform.classList.remove('active');
  recognition.start();
}

function stopListening() {
  isListening = false;
  micBtn.classList.remove('listening');
  micRipple.classList.remove('animate');
  if (recognition) recognition.stop();
}

// ── Speech Recognition ───────────────────────────────────────────────────────
function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    document.getElementById('mic-hint').textContent = '⚠️ Use Chrome/Edge for voice input';
    return;
  }
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map(r => r[0].transcript).join('');
    if (event.results[event.results.length - 1].isFinal) {
      handleUserSpeech(transcript.trim());
    }
  };
  recognition.onend = () => {
    if (isListening) {
      isListening = false;
      micBtn.classList.remove('listening');
      micRipple.classList.remove('animate');
    }
  };
  recognition.onerror = (e) => {
    console.warn('STT error:', e.error);
    isListening = false;
    micBtn.classList.remove('listening');
    setStatus(State.IDLE, 'Ready — tap mic to speak');
    if (e.error !== 'aborted') appendTurn('agent', "I didn't catch that — please try again.");
  };
}

// ── Send user speech to server ────────────────────────────────────────────────
async function handleUserSpeech(text) {
  if (!text) return;
  stopListening();
  appendTurn('user', text);
  setStatus(State.THINKING, 'Thinking…');
  micBtn.classList.add('disabled');

  // Try WebSocket first, fallback to REST
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'speech_text', text, session_id: sessionId }));
  } else {
    await sendViaRest(text);
  }
}

async function sendViaRest(text) {
  // WebSocket fallback: could be implemented as a REST endpoint
  appendTurn('agent', "Connection lost. Please refresh to reconnect.");
  setStatus(State.IDLE, 'Disconnected');
  micBtn.classList.remove('disabled');
}

// ── Handle agent response ─────────────────────────────────────────────────────
async function handleAgentResponse(data) {
  appendTurn('agent', data.text);
  updateStatePanel(data);

  if (data.booking_triggered && data.appointment_summary) {
    showAppointmentCard(data.appointment_summary);
  }

  await speak(data.text, data.audio_base64);
  setStatus(State.IDLE, 'Ready — tap mic to speak');
  micBtn.classList.remove('disabled');
}

// ── TTS ───────────────────────────────────────────────────────────────────────
async function speak(text, audioBase64) {
  setStatus(State.SPEAKING, 'Speaking…');
  waveform.classList.add('active');

  if (audioBase64) {
    await playBase64Audio(audioBase64, text);
  } else {
    await browserSpeak(text);
  }

  waveform.classList.remove('active');
}

function playBase64Audio(base64, fallbackText) {
  return new Promise((resolve) => {
    const audio = new Audio('data:audio/mp3;base64,' + base64);
    currentAudio = audio;
    audio.onended = () => { currentAudio = null; resolve(); };
    audio.onerror = () => { currentAudio = null; browserSpeak(fallbackText || '').then(resolve); };
    audio.play().catch(() => { currentAudio = null; browserSpeak(fallbackText || '').then(resolve); });
  });
}

function browserSpeak(text) {
  return new Promise((resolve) => {
    if (!synth || !text) { resolve(); return; }
    synth.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 1.0; utt.pitch = 1.0;
    const voices = synth.getVoices();
    const femalePrefs = ['Samantha','Nicky','Karen','Moira','Google UK English Female','Microsoft Zira','Microsoft Emma','Google US English'];
    const preferred = femalePrefs.map(n => voices.find(v => v.name.includes(n))).find(Boolean)
      || voices.find(v => v.lang === 'en-US' && (v.name.toLowerCase().includes('female') || v.name.includes('Samantha') || v.name.includes('Karen')))
      || voices.find(v => v.lang === 'en-US');
    if (preferred) utt.voice = preferred;
    utt.onend = resolve;
    utt.onerror = resolve;
    synth.speak(utt);
  });
}

function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  synth?.cancel();
  waveform.classList.remove('active');
  setStatus(State.IDLE, 'Ready — tap mic to speak');
  micBtn.classList.remove('disabled');
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function setStatus(state, text) {
  appState = state;
  statusText.textContent = text;
  statusBar.className = `status-bar ${state}`;
}

let turnCount = 0;
function appendTurn(role, text) {
  const id = 'turn-' + (++turnCount);
  const time = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  const avatar = role === 'agent' ? '🤖' : '👤';
  transcriptEl.insertAdjacentHTML('beforeend', `
    <div class="turn ${role}" id="${id}">
      <div class="turn-avatar">${avatar}</div>
      <div>
        <div class="turn-bubble">${escHtml(text)}</div>
        <div class="turn-time">${time}</div>
      </div>
    </div>
  `);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function updateStatePanel(data) {
  if (stateEl && data.state) {
    stateEl.textContent = data.state.replace('_', ' ');
  }
  if (collectedEl && data.collected) {
    const c = data.collected;
    collectedEl.innerHTML = Object.entries(c).length ? Object.entries(c).map(([k,v]) => `
      <div class="collected-item">
        <div class="collected-label">${k.replace('_',' ')}</div>
        <div class="collected-value">${escHtml(String(v))}</div>
      </div>`).join('') : '<p style="font-size:11px;color:#64748b">Collecting info…</p>';
  }
}

function showAppointmentCard(data) {
  apptCard.classList.add('show');
  const fields = [
    ['Customer', data.name],
    ['Service', data.service_type],
    ['Address', data.address],
    ['Time', data.preferred_time],
    ['Phone', data.phone],
  ].filter(([,v]) => v);
  document.getElementById('appt-details').innerHTML = fields.map(([l,v]) => `
    <div class="appt-row"><span class="appt-label">${l}</span><span class="appt-value">${escHtml(String(v))}</span></div>
  `).join('');
}

// New call
document.getElementById('new-call-btn')?.addEventListener('click', () => {
  if (!confirm('Start a new call? Current session will end.')) return;
  transcriptEl.innerHTML = '';
  apptCard.classList.remove('show');
  if (collectedEl) collectedEl.innerHTML = '<p style="font-size:11px;color:#64748b">Collecting info…</p>';
  stopSpeaking();
  if (ws) ws.close();
  startSession();
});

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
