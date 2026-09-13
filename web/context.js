// Local, bounded transcript relay. No summarizer, model calls, disk storage,
// speaker identification, or GitHub action is triggered by receiving speech.
const INPUT_TYPE = 'session.input_transcript.delta';
const MAX_QUEUE_EVENTS = 200;
const MAX_QUEUE_CHARACTERS = 20000;
const MAX_EVENT_CHARACTERS = 4000;
const MAX_BATCH_CHARACTERS = 8000;

export function createMeetingContext({ sessionId, fetchImpl = globalThis.fetch, onError = () => {} }) {
  if (typeof sessionId !== 'string' || !sessionId.trim()) throw new TypeError('Meeting context needs a Live session ID.');
  let queue = [];
  let characters = 0;
  let dropped = 0;
  let sequence = 1;
  let pending = null;
  let running = null;
  let timer = null;
  let closed = false;
  let ending = null;
  const abort = new AbortController();

  function schedule() {
    if (closed || timer || (!queue.length && !pending && !dropped)) return;
    timer = setTimeout(() => {
      timer = null;
      flush().catch(() => {});
    }, 1000);
  }
  function add(event) {
    if (closed) return;
    if (
      event?.type !== INPUT_TYPE || typeof event.event_id !== 'string' || !event.event_id.length || event.event_id.length > 256 ||
      typeof event.delta !== 'string' || !event.delta.length || event.delta.length > MAX_EVENT_CHARACTERS || event.delta.includes('\0') ||
      !Number.isFinite(event.start_ms) || !Number.isFinite(event.end_ms) || event.start_ms < 0 || event.end_ms < event.start_ms || event.end_ms > 86400000
    ) {
      // Ignore assistant/non-transcript events completely. A missing/invalid
      // participant fragment is reported as missing evidence, never invented.
      if (event?.type === INPUT_TYPE) { dropped += 1; schedule(); }
      return;
    }
    queue.push({ type: event.type, event_id: event.event_id, delta: event.delta, start_ms: event.start_ms, end_ms: event.end_ms });
    characters += event.delta.length;
    while (queue.length > MAX_QUEUE_EVENTS || characters > MAX_QUEUE_CHARACTERS) {
      characters -= queue.shift().delta.length;
      dropped += 1;
    }
    schedule();
  }
  function nextBatch() {
    const events = [];
    let count = 0;
    while (queue.length && events.length < 32 && count + queue[0].delta.length <= MAX_BATCH_CHARACTERS) {
      const event = queue.shift();
      events.push(event);
      count += event.delta.length;
      characters -= event.delta.length;
    }
    const batch = { session_id: sessionId, batch_sequence: sequence, events, dropped_before: dropped };
    dropped = 0;
    return batch;
  }
  async function deliver() {
    while (!closed && (pending || queue.length || dropped)) {
      pending ??= nextBatch();
      const response = await fetchImpl('/api/meeting/context', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pending), signal: abort.signal,
      });
      if (closed) return;
      if (!response.ok) throw new Error(`Meeting context could not be saved (HTTP ${response.status}). Ask again after the connection recovers.`);
      const receipt = await response.json();
      if (closed) return;
      if (receipt?.ok !== true || receipt.batch_sequence !== sequence) throw new Error('Meeting context returned an invalid receipt.');
      pending = null;
      sequence += 1;
    }
  }
  function flush() {
    if (closed) return Promise.reject(new Error('Meeting context has ended.'));
    if (running) return running;
    if (timer) { clearTimeout(timer); timer = null; }
    running = deliver().catch(error => {
      if (!closed) {
        try { onError(error.message); } catch { /* A view callback cannot discard evidence. */ }
      }
      throw error;
    }).finally(() => { running = null; schedule(); });
    return running;
  }
  function stop() {
    if (ending) return ending;
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    abort.abort();
    queue = [];
    characters = 0;
    dropped = 0;
    pending = null;
    // Tombstone only this evidence buffer. In-flight writes/approval receipts
    // retain their existing lifecycle and are not canceled or forgotten here.
    ending = Promise.resolve().then(() => fetchImpl('/api/meeting/context/end', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
      body: JSON.stringify({ session_id: sessionId }),
    })).then(response => {
      if (!response.ok) throw new Error('Meeting context cleanup could not be delivered; the local session expiry will clear it.');
    }).catch(error => {
      try { onError(error.message); } catch { /* Best-effort close on page unload. */ }
    });
    return ending;
  }
  return { add, flush, stop };
}
