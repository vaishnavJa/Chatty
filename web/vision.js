// Incoming meeting pixels only. This helper never presents a screen to Meet,
// adds video to a peer connection, or uploads frames on a timer.
export const MAX_FRAME_EDGE = 1280;
export const MAX_FRAME_BYTES = 262144;
const READY_TIMEOUT_MS = 3000;
const REQUEST_INTERVAL_MS = 1500;

export function frameSize(width, height, maximum = MAX_FRAME_EDGE) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error('The selected meeting tab has no readable video frame yet.');
  }
  const scale = Math.min(1, maximum / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** Owns a video-only stream for exactly one Live session; disabled until enabled. */
export function createMeetingVision({ stream, sessionId, onState = () => {} }) {
  if (typeof sessionId !== 'string' || !sessionId.trim()) throw new TypeError('Vision needs the current Live session ID.');
  const tracks = stream?.getVideoTracks() ?? [];
  if (!tracks.length || stream.getAudioTracks().length || tracks.some(track => track.readyState !== 'live')) {
    throw new Error('Vision needs a live video-only stream from the selected meeting tab.');
  }
  const video = document.createElement('video');
  const canvas = document.createElement('canvas');
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  let enabled = false;
  let ended = false;
  let revision = 0;
  let request = null;
  let lastRequest = -Infinity;
  const listeners = [];
  const state = (name, detail = {}) => onState(name, detail);
  function listen(target, event, handler) {
    target.addEventListener(event, handler);
    listeners.push(() => target.removeEventListener(event, handler));
  }
  function blank() { canvas.width = 0; canvas.height = 0; }
  function clear() {
    revision += 1;
    request?.abort();
    request = null;
    blank();
  }
  function valid() {
    if (ended || !enabled) throw new Error('Meeting vision is off. Enable screen context before asking about the screen.');
    if (tracks.some(track => track.readyState !== 'live' || track.muted || !track.enabled)) {
      throw new Error('The meeting video source is unavailable. Select the meeting tab again.');
    }
  }
  function setEnabled(value) {
    if (ended) throw new Error('Meeting vision ended. Start a new session.');
    const next = Boolean(value);
    if (enabled !== next) clear();
    enabled = next;
    if (enabled) video.play().catch(() => { if (!ended && enabled) state('error', { message: 'Click Enable screen context again to allow video capture.' }); });
    else video.pause();
    state(enabled ? 'ready' : 'off');
  }
  async function captureFrame() {
    valid();
    const version = revision;
    if (video.readyState < 2) {
      await new Promise((resolve, reject) => {
        const finish = error => {
          clearTimeout(timer);
          video.removeEventListener('loadeddata', ready);
          video.removeEventListener('error', failed);
          if (error) reject(error); else resolve();
        };
        const ready = () => finish();
        const failed = () => finish(new Error('The selected meeting video could not be decoded.'));
        const timer = setTimeout(() => finish(new Error('The meeting tab has no readable frame yet. Try again once its video is visible.')), READY_TIMEOUT_MS);
        video.addEventListener('loadeddata', ready, { once: true });
        video.addEventListener('error', failed, { once: true });
        if (video.readyState >= 2) ready();
      });
    }
    valid();
    if (version !== revision) throw new DOMException('Meeting vision source changed.', 'AbortError');
    const context = canvas.getContext('2d');
    if (!context) throw new Error('This browser cannot capture meeting pixels.');
    try {
      for (const [maximum, quality] of [[1280, 0.75], [1280, 0.5], [960, 0.5], [720, 0.4]]) {
        const size = frameSize(video.videoWidth, video.videoHeight, maximum);
        canvas.width = size.width;
        canvas.height = size.height;
        context.drawImage(video, 0, 0, size.width, size.height);
        const image = canvas.toDataURL('image/jpeg', quality);
        if (!image.startsWith('data:image/jpeg;base64,')) throw new Error('This browser did not produce a JPEG frame.');
        const encoded = image.slice('data:image/jpeg;base64,'.length);
        const bytes = encoded.length * 3 / 4 - (encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0);
        if (bytes <= MAX_FRAME_BYTES) {
          return { image_data_url: image, ...size, captured_at: Date.now() };
        }
      }
      throw new Error('The selected frame is too large. Enlarge the shared content and try again.');
    } finally { blank(); }
  }
  async function analyze(question, { callId, signal } = {}) {
    valid();
    if (typeof question !== 'string' || !question.trim() || question.length > 2000) throw new Error('Ask a screen question of at most 2000 characters.');
    if (typeof callId !== 'string' || !callId.trim()) throw new Error('A screen tool call ID is required.');
    if (request) throw new Error('A screen question is already being processed.');
    if (Date.now() - lastRequest < REQUEST_INTERVAL_MS) throw new Error('Wait a moment before asking another screen question.');
    signal?.throwIfAborted();
    const version = revision;
    const pending = new AbortController();
    request = pending;
    const abort = () => pending.abort(signal.reason);
    signal?.addEventListener('abort', abort, { once: true });
    try {
      const frame = await captureFrame();
      pending.signal.throwIfAborted();
      valid();
      if (version !== revision) throw new DOMException('Meeting vision source changed.', 'AbortError');
      lastRequest = Date.now();
      state('analyzing', { captured_at: frame.captured_at });
      const response = await fetch('/api/vision/analyze', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: pending.signal,
        body: JSON.stringify({ session_id: sessionId, call_id: callId, question, frame }),
      });
      pending.signal.throwIfAborted();
      if (version !== revision || ended || !enabled) throw new DOMException('Meeting vision changed while the answer was being prepared.', 'AbortError');
      if (!response.ok) throw new Error(`Screen analysis failed (HTTP ${response.status}). Try again or inspect the shared content directly.`);
      const result = await response.json();
      pending.signal.throwIfAborted();
      if (version !== revision || ended || !enabled) throw new DOMException('Meeting vision changed while the answer was being prepared.', 'AbortError');
      if (result?.call_id !== callId || typeof result.output !== 'string') throw new Error('Screen analysis returned an invalid tool receipt.');
      state('ready', { captured_at: frame.captured_at });
      return result;
    } finally {
      signal?.removeEventListener('abort', abort);
      if (request === pending) request = null;
    }
  }
  function stop() {
    if (ended) return;
    ended = true;
    enabled = false;
    clear();
    listeners.forEach(remove => remove());
    video.pause();
    video.srcObject = null;
    tracks.forEach(track => track.stop());
    state('off');
  }
  tracks.forEach(track => {
    listen(track, 'ended', stop);
    listen(track, 'mute', () => { clear(); state('unavailable'); });
  });
  listen(stream, 'inactive', stop);
  if (globalThis.addEventListener) listen(globalThis, 'pagehide', stop);
  return { setEnabled, captureFrame, analyze, clear, stop, get enabled() { return enabled; } };
}
