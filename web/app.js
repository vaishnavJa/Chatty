import { captureInput } from './media.js';
import { connectLive } from './live.js';
import { DemoController } from './controller.js';

const $ = id => document.getElementById(id);
const controls = {
  start: $('start-button'), stop: $('stop-button'), resume: $('resume-button'),
  end: $('end-button'), summary: $('summary-button'), download: $('download-button'), source: $('audio-source'),
};
let current = null;
let displayed = null;
let phase = 'idle';
let health = null;
let lastError = '';
let sequence = 0;
const toolViews = new WeakMap();
const toolLabels = { list_open_pull_requests: 'Open pull requests', list_open_issues: 'Open issues', get_recent_commits: 'Recent commits', list_recent_commits: 'Recent commits', get_open_pull_requests: 'Open pull requests', list_pull_requests: 'Pull requests', search_repo: 'Search repository', search_repository: 'Search repository', create_issue: 'Create GitHub issue' };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function showError(message) {
  lastError = message || 'Something went wrong. End the session and try again.';
  $('error-text').textContent = lastError;
  $('error-banner').hidden = false;
}
function clearError() { lastError = ''; $('error-banner').hidden = true; }
function active(controller) { return current?.controller === controller && controller.active; }

function renderStatus() {
  const ready = phase === 'ready' && !!current?.controller.handle;
  const busy = !!current;
  const speech = displayed?.speech;
  controls.start.disabled = busy || health?.openai_configured === false;
  controls.source.disabled = busy;
  controls.stop.disabled = !ready || speech === 'stopped';
  controls.resume.disabled = !ready;
  controls.end.disabled = !busy;
  controls.summary.disabled = !ready || !displayed?.transcripts.length;
  controls.download.disabled = !displayed?.transcripts.length;
  controls.start.textContent = phase === 'capturing' ? 'Selecting audio…' : phase === 'connecting' ? 'Connecting…' : '▶ Start session';
  const labels = { idle: health ? 'Ready to connect' : 'Checking setup', capturing: 'Select audio source', connecting: 'Connecting to Live', ready: 'Connected to Live', reconnecting: 'Reconnecting', closing: 'Ending session', closed: 'Session ended', error: 'Connection failed' };
  $('connection-status').textContent = labels[phase] ?? phase;
  $('connection-pill').className = `pill ${ready ? 'connected' : phase === 'error' ? 'error' : ''}`;
  $('session-id').textContent = current?.controller.handle?.sessionId ?? (busy ? 'Starting a new session' : 'No active session');
  $('voice-icon').classList.toggle('live', ready && speech === 'listening');
  $('speech-dot').classList.toggle('live', ready);
  let title = 'Ready when you are.';
  let description = controls.source.value === 'meeting-tab' ? 'Select your Meet tab and enable Share tab audio.' : 'Start with your microphone for a quick conversation.';
  let input = 'Microphone off';
  if (busy) {
    title = phase === 'capturing' ? 'Choose what Chatty hears.' : phase === 'connecting' ? 'Making the connection.' : 'Listening to the conversation.';
    description = phase === 'capturing' ? 'Allow microphone access, or select the meeting tab with audio.' : phase === 'connecting' ? 'Connecting your audio to OpenAI Live.' : 'Ask about your project or request an action.';
    input = ready ? `${current.source === 'microphone' ? 'Microphone' : 'Meeting tab'} on · replies enabled` : 'Preparing audio';
    if (ready && speech === 'waiting') { title = 'Listening for “Hey Chatty”.'; description = 'Wake Chatty when you need project context or an action.'; input = 'Meeting audio on · replies muted'; }
    if (ready && speech === 'stopped') { title = 'Quiet, until you need me.'; description = 'Say “Hey Chatty” or click Resume to hear replies again.'; input = 'Input on · replies muted'; }
    if (phase === 'reconnecting') { title = 'Reconnecting…'; description = 'The audio connection was interrupted.'; input = 'Connection interrupted'; }
  } else if (phase === 'error') { title = 'Let’s reconnect.'; description = 'Check the error above, then start a new session.'; }
  else if (phase === 'closed') { title = 'Conversation saved on this page.'; description = 'Download the transcript or start a fresh session.'; }
  $('session-title').textContent = title;
  $('session-description').textContent = description;
  $('speech-status').textContent = input;
  const summaryStates = { canceled: 'Summary request canceled when Chatty was stopped.', requested: 'Summary requested. Waiting for Live to accept the instruction…', accepted: 'Summary instruction accepted. Watch the conversation for Chatty’s spoken summary.', error: 'The summary request failed. Check the error above and try again.' };
  $('summary-status').textContent = summaryStates[displayed?.summary] ?? 'Ask for decisions, open questions, and action items from this conversation.';
}

function renderCaptions(controller) {
  const stream = $('captions');
  const follow = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 75;
  const rows = [];
  const lastByRole = new Map();
  for (const fragment of controller.transcripts) {
    let row = lastByRole.get(fragment.role);
    const gap = typeof fragment.start_ms === 'number' && typeof row?.end === 'number' ? fragment.start_ms - row.end : 0;
    if (!row || gap > 1800 || gap < -1800) {
      row = { role: fragment.role, text: '', start: fragment.start_ms, end: fragment.end_ms };
      rows.push(row);
      lastByRole.set(fragment.role, row);
    }
    row.text += fragment.delta;
    row.end = fragment.end_ms;
  }
  if (!rows.length) return;
  const nodes = rows.map(row => {
    const card = element('article', `caption-row ${row.role}`);
    card.append(element('span', 'caption-avatar', row.role === 'chatty' ? 'C' : 'Y'));
    const header = element('div', 'caption-heading');
    header.append(element('span', '', row.role === 'chatty' ? 'Chatty' : controller.source === 'meeting-tab' ? 'Meeting participant' : 'You'));
    if (typeof row.start === 'number') header.append(element('span', 'caption-time', `${Math.floor(row.start / 60000)}:${String(Math.floor(row.start / 1000) % 60).padStart(2, '0')}`));
    card.append(header, element('p', 'caption-text', row.text));
    return card;
  });
  stream.replaceChildren(...nodes);
  $('caption-count').textContent = 'Live captions · approximate grouping';
  if (follow) stream.scrollTop = stream.scrollHeight;
}

function renderTools(controller) {
  const signature = JSON.stringify([...controller.calls.values()].map(call => [call.call_id, call.status, call.message, call.output])) + controller.speech + controller.active;
  if (toolViews.get(controller) === signature) return;
  toolViews.set(controller, signature);
  const container = $('tool-activity');
  $('action-count').textContent = String(controller.calls.size);
  if (!controller.calls.size) return;
  const labels = { pending: 'Pending', running: 'Working…', approval: 'Review required', complete: 'Confirmed', error: 'Failed', rejected: 'Not created', uncertain: 'Check GitHub', canceled: 'Canceled' };
  const cards = [...controller.calls.values()].reverse().map(call => {
    const card = element('article', `tool-card ${call.status}`);
    const heading = element('div', 'tool-heading');
    heading.append(element('strong', '', toolLabels[call.name] ?? call.name.replaceAll('_', ' ')), element('span', 'tool-state', labels[call.status] ?? call.status));
    card.append(heading);
    if (call.name === 'create_issue') {
      card.append(element('p', '', call.arguments.title ?? 'Issue request'));
      if (call.status === 'approval') {
        card.append(element('pre', 'tool-body', call.arguments.body));
        const buttons = element('div', 'approval-actions');
        const approve = element('button', 'button primary', 'Create issue');
        const reject = element('button', 'button', 'Reject');
        approve.disabled = !active(controller) || controller.speech !== 'listening';
        reject.disabled = !active(controller);
        approve.addEventListener('click', () => controller.approve(call.call_id));
        reject.addEventListener('click', () => controller.reject(call.call_id));
        buttons.append(approve, reject);
        card.append(buttons);
      }
    }
    if (call.message) card.append(element('p', '', call.message));
    for (const url of call.links) {
      const link = element('a', '', `${url.replace('https://github.com/', '')} ↗`);
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      card.append(link);
    }
    if (call.result) {
      const details = element('details');
      details.append(element('summary', '', 'View returned data'), element('pre', '', JSON.stringify(call.result, null, 2)));
      card.append(details);
    }
    return card;
  });
  container.replaceChildren(...cards);
}
function render(controller) {
  if (controller !== displayed) return;
  renderStatus(); renderCaptions(controller); renderTools(controller);
}
async function executeTool(body, signal) {
  const response = await fetch('/api/tools/execute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (!response.ok) {
    let message = `Tool request failed (HTTP ${response.status}).`;
    try {
      const data = await response.json();
      if (typeof data.error === 'string') message = data.error;
      else if (typeof data.detail === 'string') message = data.detail;
    } catch { /* Keep the HTTP status if the error body isn't JSON. */ }
    throw new Error(message);
  }
  return response.json();
}
function resetViews() {
  $('captions').replaceChildren(element('div', 'empty-state', 'Listening captions will appear here.'));
  $('tool-activity').replaceChildren(element('div', 'activity-empty', 'Repository lookups and issue receipts will appear here.'));
  $('action-count').textContent = '0';
  $('caption-count').textContent = 'Live captions';
}

async function startSession() {
  if (current) return;
  clearError();
  const source = controls.source.value;
  const run = { id: ++sequence, source, abort: new AbortController(), capture: null, handle: null, controller: null };
  run.controller = new DemoController({ source, execute: executeTool, onChange: render, onError: message => { if (current === run) showError(message); } });
  current = run; displayed = run.controller; phase = 'capturing'; resetViews(); renderStatus();
  try {
    // Call capture directly from the Start gesture, before any network await.
    const capture = await captureInput(source);
    if (current !== run) { capture.stop(); return; }
    run.capture = capture;
    phase = 'connecting'; renderStatus();
    const handle = await connectLive({
      stream: capture.stream, signal: run.abort.signal,
      onEvent: event => run.controller.event(event),
      onState: (state, details = {}) => {
        if (current !== run) return;
        if (state === 'error') showError(details.message);
        if (state === 'playback-blocked') showError(details.message ?? 'Click Resume to allow audio playback.');
        if (state === 'connecting' || state === 'ready' || state === 'reconnecting' || state === 'closing') phase = state;
        if (state === 'closed') {
          run.controller.end(); run.capture?.stop(); current = null;
          phase = lastError ? 'error' : 'closed';
        }
        renderStatus();
      },
    });
    if (current !== run) { handle.close(); capture.stop(); return; }
    run.handle = handle;
    run.controller.attach(handle);
    phase = 'ready'; renderStatus();
  } catch (error) {
    run.capture?.stop();
    run.controller.end();
    if (current === run) current = null;
    if (run.id !== sequence) return;
    if (run.abort.signal.aborted) phase = 'closed';
    else { phase = 'error'; showError(error.message); }
    renderStatus();
  }
}
function endSession() {
  const run = current;
  if (!run) return;
  current = null;
  ++sequence;
  run.controller.end();
  // End invalidates callbacks before stopping tracks or resolving a chooser.
  run.abort.abort(); run.capture?.stop();
  run.handle?.close();
  phase = 'closed'; renderStatus();
}
function downloadTranscript() {
  if (!displayed?.transcripts.length) return;
  const text = ['# Chatty conversation', '', 'Captured transcript fragments; not a verified meeting summary.', ''];
  let lastRole;
  for (const fragment of displayed.transcripts) {
    if (lastRole !== fragment.role) { text.push(`\n\n${fragment.role === 'chatty' ? 'Chatty' : 'Participant'}: `); lastRole = fragment.role; }
    text.push(fragment.delta);
  }
  const receipts = [...displayed.calls.values()].filter(call => call.links.length);
  if (receipts.length) text.push('\n\nSources and action receipts\n', ...receipts.flatMap(call => call.links.map(url => `\n- ${call.name} (${call.status}): ${url}`)));
  const url = URL.createObjectURL(new Blob([text.join('')], { type: 'text/markdown' }));
  const link = element('a'); link.href = url; link.download = `chatty-conversation-${new Date().toISOString().slice(0, 10)}.md`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
controls.start.addEventListener('click', startSession);
controls.end.addEventListener('click', endSession);
controls.stop.addEventListener('click', () => current?.controller.stop());
controls.resume.addEventListener('click', () => { clearError(); current?.controller.resume(); });
controls.summary.addEventListener('click', () => current?.controller.summarize());
controls.download.addEventListener('click', downloadTranscript);
controls.source.addEventListener('change', renderStatus);
$('dismiss-error').addEventListener('click', clearError);
window.addEventListener('pagehide', endSession);
renderStatus();
fetch('/api/health').then(async response => {
  if (!response.ok) throw new Error(`Local server health check failed (HTTP ${response.status}).`);
  health = await response.json();
  if (health.ok !== true && health.status !== 'ok') throw new Error('Local server is not ready.');
  $('health-dot').classList.toggle('healthy', health.openai_configured === true);
  $('health-label').textContent = health.openai_configured ? 'Live configured · repository tools available' : 'OpenAI key is not configured';
  if (!health.openai_configured) showError('Configure OPENAI_API_KEY on the local server, restart it, and refresh this page.');
  renderStatus();
}).catch(error => { $('health-label').textContent = 'Local server unavailable'; if (!current) showError(error.message); });
