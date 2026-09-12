import { captureInput, listAudioOutputs, requestAudioOutputs } from './media.js';
import { createMeetingVision } from './vision.js';
import { connectLive } from './live.js';
import { DemoController, reviewTarget, validateCapabilities } from './controller.js';

const $ = id => document.getElementById(id);
const controls = {
  start: $('start-button'), stop: $('stop-button'), resume: $('resume-button'),
  output: $('output-device'), devices: $('audio-devices-button'), vision: $('screen-context'),
  end: $('end-button'), summary: $('summary-button'), download: $('download-button'), source: $('audio-source'),
};
let current = null;
let displayed = null;
let phase = 'idle';
let health = null;
let capabilities = null;
let outputs = [];
let loadingDevices = false;
let lastError = '';
let sequence = 0;
const toolViews = new WeakMap();

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
function loopbackOutput(device) {
  return device && !['', 'default', 'communications'].includes(device.deviceId)
    && /microsoft teams audio|blackhole|loopback|soundflower|vb.?audio|virtual|cable/i.test(device.label);
}
function chosenOutput() { return outputs.find(device => device.deviceId === controls.output.value); }
function refreshOutputs(devices) {
  const chosen = controls.output.value;
  outputs = devices;
  const meeting = controls.source.value === 'meeting-tab';
  const placeholder = element('option', '', meeting ? 'Choose a virtual audio output' : 'System default · microphone test');
  placeholder.value = '';
  const options = devices.filter(device => device.deviceId && device.deviceId !== 'default').map(device => {
    const option = element('option', '', device.label || 'Audio output (enable devices to identify)');
    option.value = device.deviceId;
    option.disabled = meeting && !loopbackOutput(device);
    return option;
  });
  controls.output.replaceChildren(placeholder, ...options);
  if (devices.some(device => device.deviceId === chosen && (!meeting || loopbackOutput(device)))) controls.output.value = chosen;
  renderStatus();
}
async function enableAudioDevices() {
  if (current || loadingDevices) return;
  loadingDevices = true; renderStatus();
  try { refreshOutputs(await requestAudioOutputs()); }
  catch (error) { showError(error.message); }
  finally { loadingDevices = false; renderStatus(); }
}

function renderStatus() {
  const ready = phase === 'ready' && !!current?.controller.handle;
  const busy = !!current;
  const speech = displayed?.speech;
  const meeting = controls.source.value === 'meeting-tab';
  controls.start.disabled = busy || loadingDevices || health?.openai_configured !== true || !capabilities || (meeting && !loopbackOutput(chosenOutput()));
  controls.output.disabled = busy || loadingDevices;
  controls.devices.disabled = busy || loadingDevices;
  controls.devices.textContent = loadingDevices ? 'Enabling devices…' : 'Enable audio devices';
  controls.vision.disabled = !meeting || (busy && !current?.vision);
  $('output-help').textContent = meeting ? 'Choose a virtual audio device, then use the same device as your unmuted Meet microphone. Keep Meet speakers on normal speakers or headphones.' : 'Microphone tests play through the selected output.';
  if (current?.outputActivityAvailable === false) $('output-help').textContent += ' Answer-end detection is unavailable: use Stop speaking; each wake expires after 90 seconds.';
  const visionStates = { ready: 'Screen context enabled. A snapshot is sent only for a screen question.', analyzing: 'Reading the requested meeting snapshot…', unavailable: 'The incoming screen source is unavailable.', off: 'Screen context is off.' };
  $('screen-context-status').textContent = current?.vision ? visionStates[current.visionState] ?? 'Preparing incoming screen context…' : controls.vision.checked ? 'A single current snapshot will be sent only when you ask about the screen.' : 'Off. Enable before starting a meeting session. One snapshot is sent only when you ask about the screen.';
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
    if (ready && speech === 'waiting') { title = 'Listening for “Chatty”.'; description = 'Wake Chatty when you need project context or an action.'; input = 'Meeting audio on · replies muted'; }
    if (ready && speech === 'stopped') { title = 'Quiet, until you need me.'; description = 'Say “Chatty” or click Resume to hear replies again.'; input = 'Input on · replies muted'; }
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
  const signature = JSON.stringify([...controller.calls.values()].map(call => [call.call_id, call.status, call.message, call.proposal, call.output])) + controller.speech + controller.active;
  if (toolViews.get(controller) === signature) return;
  toolViews.set(controller, signature);
  const container = $('tool-activity');
  $('action-count').textContent = String(controller.calls.size);
  if (!controller.calls.size) return;
  const labels = { pending: 'Pending', running: 'Working…', approval: 'Spoken approval', complete: 'Confirmed', error: 'Failed', rejected: 'Not applied', uncertain: 'Check GitHub', canceled: 'Canceled' };
  const cards = [...controller.calls.values()].reverse().map(call => {
    const card = element('article', `tool-card ${call.status}`);
    const heading = element('div', 'tool-heading');
    heading.append(element('strong', '', call.capability?.label ?? call.name.replaceAll('_', ' ')), element('span', 'tool-state', labels[call.status] ?? call.status));
    card.append(heading);
    if (call.capability?.requires_approval) {
      card.append(element('p', '', `Target: ${reviewTarget(call)}`));
      if (call.status === 'approval') {
        if (call.proposal) card.append(element('p', '', call.proposal));
        const proposal = element('details');
        proposal.append(element('summary', '', 'View exact proposed change'), element('pre', 'tool-body', JSON.stringify(call.arguments, null, 2)));
        card.append(proposal);
        if (call.capability.destructive) card.append(element('p', '', 'This change can remove data or change repository history. Listen to the exact proposal before replying.'));
        const buttons = element('div', 'approval-actions');
        const reject = element('button', 'button', 'Cancel change');
        reject.disabled = !active(controller);
        reject.addEventListener('click', () => controller.reject(call.call_id));
        buttons.append(reject);
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
  if (active(controller) && current.lastSpeech !== controller.speech) {
    current.lastSpeech = controller.speech;
    if (controller.speech !== 'listening') current.vision?.clear();
  }
  renderStatus(); renderCaptions(controller); renderTools(controller);
}
async function postJson(path, body, signal) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (!response.ok) {
    let message = `Tool request failed (HTTP ${response.status}).`;
    try {
      const data = await response.json();
      if (typeof data.error === 'string') message = data.error;
      else if (typeof data.error?.message === 'string') message = data.error.message;
      else if (typeof data.detail === 'string') message = data.detail;
    } catch { /* Keep the HTTP status if the error body isn't JSON. */ }
    throw new Error(message);
  }
  return response.json();
}
const executeTool = (body, signal) => postJson('/api/tools/execute', body, signal);
const approveByVoice = (action, body, signal) => postJson(`/api/approvals/${action}`, body, signal);

function resetViews() {
  $('captions').replaceChildren(element('div', 'empty-state', 'Listening captions will appear here.'));
  $('tool-activity').replaceChildren(element('div', 'activity-empty', 'Repository and project lookups and change receipts will appear here.'));
  $('action-count').textContent = '0';
  $('caption-count').textContent = 'Live captions';
}

async function startSession() {
  if (current || health?.openai_configured !== true || !capabilities || (controls.source.value === 'meeting-tab' && !loopbackOutput(chosenOutput()))) return;
  clearError();
  const source = controls.source.value;
  const run = { id: ++sequence, source, outputDeviceId: controls.output.value, screenContext: controls.vision.checked, abort: new AbortController(), capture: null, handle: null, controller: null, vision: null, visionState: 'off' };
  run.controller = new DemoController({ source, capabilities, approval: approveByVoice, execute: (body, signal) => {
    if (body.name !== 'read_meeting_screen') return executeTool(body, signal);
    if (!run.vision?.enabled || current !== run) throw new Error('Incoming screen context is off. Enable it before starting a meeting session.');
    return run.vision.analyze(body.arguments.question, { callId: body.call_id, signal });
  }, onChange: render, onError: message => { if (current === run) showError(message); } });
  current = run; displayed = run.controller; phase = 'capturing'; resetViews(); renderStatus();
  try {
    // Call capture directly from the Start gesture, before any network await.
    const capture = await captureInput(source, { keepVideo: source === 'meeting-tab' && run.screenContext });
    if (current !== run) { capture.stop(); return; }
    run.capture = capture;
    phase = 'connecting'; renderStatus();
    const handle = await connectLive({
      stream: capture.stream, signal: run.abort.signal, outputDeviceId: run.outputDeviceId,
      onOutputActivity: value => run.controller.outputActivity(value),
      onInputActivity: (value, details) => run.controller.inputActivity(value, details),
      onEvent: event => run.controller.event(event),
      onState: (state, details = {}) => {
        if (current !== run) return;
        if (state === 'error') showError(details.message);
        if (state === 'output-activity-unavailable') run.outputActivityAvailable = false;
        if (state === 'input-activity-unavailable') showError('Spoken approval needs working input audio activity detection. End the session and reconnect the audio source.');
        if (state === 'playback-blocked') showError(details.message ?? 'Click Resume to allow audio playback.');
        if (state === 'connecting' || state === 'ready' || state === 'reconnecting' || state === 'closing') phase = state;
        if (state === 'closed') {
          run.controller.end(); run.vision?.stop(); run.capture?.stop(); current = null;
          phase = lastError ? 'error' : 'closed';
        }
        renderStatus();
      },
    });
    if (current !== run) { handle.close(); capture.stop(); return; }
    run.handle = handle;
    if (capture.videoStream) {
      run.vision = createMeetingVision({ stream: capture.videoStream, sessionId: handle.sessionId, onState: (state, details = {}) => {
        if (current !== run) return;
        run.visionState = state;
        if (state === 'error') showError(details.message);
        if (state === 'unavailable') run.vision?.clear();
        renderStatus();
      } });
      run.vision.setEnabled(run.screenContext);
    }
    run.controller.attach(handle);
    phase = 'ready'; renderStatus();
  } catch (error) {
    run.handle?.close();
    run.vision?.stop();
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
  run.abort.abort(); run.vision?.stop(); run.capture?.stop();
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
controls.output.addEventListener('change', renderStatus);
controls.devices.addEventListener('click', enableAudioDevices);
controls.vision.addEventListener('change', () => {
  try { current?.vision?.setEnabled(controls.vision.checked); }
  catch (error) { controls.vision.checked = false; showError(error.message); }
  renderStatus();
});
controls.source.addEventListener('change', () => {
  current?.vision?.stop();
  controls.vision.checked = false;
  refreshOutputs(outputs);
});
$('dismiss-error').addEventListener('click', clearError);
window.addEventListener('pagehide', endSession);
renderStatus();
listAudioOutputs().then(refreshOutputs).catch(() => { /* Permission is requested only by the explicit devices button. */ });
Promise.all([
  fetch('/api/health').then(async response => {
    if (!response.ok) throw new Error(`Local server health check failed (HTTP ${response.status}).`);
    const data = await response.json();
    if (data.ok !== true && data.status !== 'ok') throw new Error('Local server is not ready.');
    return data;
  }),
  fetch('/api/capabilities').then(async response => {
    if (!response.ok) throw new Error(`Tool capabilities could not load (HTTP ${response.status}). Restart the server and refresh.`);
    const data = await response.json();
    return validateCapabilities(data.tools);
  }),
]).then(([readyHealth, readyCapabilities]) => {
  health = readyHealth;
  capabilities = readyCapabilities;
  $('health-dot').classList.toggle('healthy', health.openai_configured === true);
  $('health-label').textContent = health.openai_configured ? `Live configured · ${Object.keys(capabilities).length} repository and project tools` : 'OpenAI key is not configured';
  if (!health.openai_configured) showError('Configure OPENAI_API_KEY on the local server, restart it, and refresh this page.');
  renderStatus();
}).catch(error => {
  capabilities = null;
  $('health-label').textContent = 'Local server setup incomplete';
  if (!current) showError(error.message);
  renderStatus();
});
