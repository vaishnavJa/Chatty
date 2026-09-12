// Application state for the documented GPT-Live data-channel event contract.
const TERMINAL = new Set(['response.completed', 'response.done', 'response.failed', 'response.incomplete', 'response.cancelled']);
const noop = () => {};
const LEGACY_CAPABILITIES = {
  list_recent_commits: { label: 'Recent commits', requires_approval: false, destructive: false },
  list_open_pull_requests: { label: 'Open pull requests', requires_approval: false, destructive: false },
  list_open_issues: { label: 'Open issues', requires_approval: false, destructive: false },
  create_issue: { label: 'Create GitHub issue', requires_approval: true, destructive: false },
};

export function validateCapabilities(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Tool capabilities are unavailable. Refresh after restarting the server.');
  const capabilities = Object.create(null);
  for (const [name, capability] of Object.entries(value)) {
    if (!capability || typeof capability.label !== 'string' || !capability.label.trim()
        || typeof capability.requires_approval !== 'boolean' || typeof capability.destructive !== 'boolean'
        || (capability.destructive && !capability.requires_approval)) throw new Error('Invalid tool capabilities. Refresh after restarting the server.');
    capabilities[name] = Object.freeze({ label: capability.label, requires_approval: capability.requires_approval, destructive: capability.destructive });
  }
  return Object.freeze(capabilities);
}

function freezeArguments(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freezeArguments);
    Object.freeze(value);
  }
  return value;
}

export function reviewTarget(call) {
  return call.name.includes('project') ? 'Configured GitHub project' : 'vaishnavJa/Chatty';
}

export function githubLinks(value) {
  const urls = new Set();
  function visit(item, depth = 0) {
    if (depth > 8 || urls.size >= 30) return;
    if (typeof item === 'string') {
      for (const raw of item.match(/https:\/\/github\.com\/[^\s<>"'\])}]+/g) ?? []) {
        try {
          const url = new URL(raw);
          if (url.protocol === 'https:' && url.hostname === 'github.com' && !url.username && !url.password) urls.add(url.href);
        } catch { /* Invalid links remain ordinary text. */ }
      }
    } else if (Array.isArray(item)) item.forEach(child => visit(child, depth + 1));
    else if (item && typeof item === 'object') Object.values(item).forEach(child => visit(child, depth + 1));
  }
  visit(value);
  return [...urls];
}

export class DemoController {
  constructor({ source = 'microphone', execute, capabilities = LEGACY_CAPABILITIES, onChange = noop, onError = noop, timers = globalThis, now = Date.now }) {
    this.source = source;
    this.capabilities = validateCapabilities(capabilities);
    this.execute = execute;
    this.onChange = onChange;
    this.onError = onError;
    this.active = true;
    this.handle = null;
    this.queue = [];
    this.events = new Set();
    this.calls = new Map();
    this.groups = new Map();
    this.delegations = new Map();
    this.canceledDelegations = new Set();
    this.canceledResponses = new Set();
    this.pendingInstructions = new Map();
    this.transcripts = [];
    this.speech = source === 'microphone' ? 'listening' : 'waiting';
    this.commandText = '';
    this.commandCursor = 0;
    this.counter = 0;
    this.abort = new AbortController();
    this.summary = 'idle';
    this.timers = timers;
    this.now = now;
    this.wakeTimer = null;
    this.quietTimer = null;
    this.outputActive = false;
    this.heardAnswer = false;
    this.needsFinalOutput = false;
    this.lastToolResultAt = -Infinity;
    this.lastOutputAt = -Infinity;
    this.busyDelegations = new Set();
  }

  changed() { this.onChange(this); }
  clearWakeTimers() {
    this.timers.clearTimeout(this.wakeTimer);
    this.timers.clearTimeout(this.quietTimer);
    this.wakeTimer = this.quietTimer = null;
  }
  beginWake() {
    if (this.source !== 'meeting-tab') return;
    this.clearWakeTimers();
    this.heardAnswer = false;
    this.needsFinalOutput = false;
    this.lastToolResultAt = this.lastOutputAt = -Infinity;
    this.wakeTimer = this.timers.setTimeout(() => {
      if (this.active && this.speech === 'listening') this.stop(true);
    }, 90000);
    this.wakeTimer?.unref?.();
  }
  outputActivity(active) {
    if (!this.active || this.source !== 'meeting-tab' || this.speech !== 'listening') return;
    const began = active && !this.outputActive;
    this.outputActive = active === true;
    if (this.outputActive) {
      this.lastOutputAt = this.now();
      this.heardAnswer = true;
      // An interim utterance already in progress when a tool completes cannot
      // count as the final answer; require a fresh audible utterance afterward.
      if (began && this.lastOutputAt >= this.lastToolResultAt) this.needsFinalOutput = false;
      this.timers.clearTimeout(this.quietTimer);
      this.quietTimer = null;
    } else this.scheduleQuiet();
  }
  scheduleQuiet() {
    if (!this.active || this.source !== 'meeting-tab' || this.speech !== 'listening'
        || this.outputActive || !this.heardAnswer || this.needsFinalOutput || this.busyDelegations.size
        || [...this.calls.values()].some(call => ['pending', 'approval', 'running'].includes(call.status))) return;
    this.timers.clearTimeout(this.quietTimer);
    this.quietTimer = this.timers.setTimeout(() => {
      this.quietTimer = null;
      if (this.active && this.speech === 'listening' && !this.outputActive && !this.needsFinalOutput
          && !this.busyDelegations.size && ![...this.calls.values()].some(call => ['pending', 'approval', 'running'].includes(call.status))) this.stop(true);
    }, 1500);
    this.quietTimer?.unref?.();
  }
  id(prefix) { return `chatty_${prefix}_${++this.counter}`; }
  send(event) {
    if (!this.active || !this.handle) return false;
    try { this.handle.send(event); return true; }
    catch (error) { this.onError(error.message); return false; }
  }
  instruction(content, purpose = 'control') {
    const event_id = this.id(purpose);
    this.pendingInstructions.set(event_id, purpose);
    if (!this.send({ type: 'session.instructions.append', event_id, delegation_id: null, content })) {
      this.pendingInstructions.delete(event_id);
      return false;
    }
    return true;
  }
  attach(handle) {
    if (!this.active) { handle.close(); return; }
    this.handle = handle;
    handle.setInputEnabled(true);
    handle.setOutputMuted(this.speech !== 'listening');
    this.instruction(this.source === 'microphone'
      ? 'Microphone demo mode: respond naturally when the user speaks; a wake word is not required. Keep answers concise. Stop speaking when asked. Do not apply repository or project changes until the application approves the exact proposed action.'
      : 'Meeting mode: listen silently until someone addresses you with the word Chatty. Answer that one addressed request briefly, including any requested tool result, then stay silent until addressed with Chatty again. Ordinary conversation is not addressed to you. When someone says Chatty stop, stop immediately. Do not perform tools while waiting. Do not apply repository or project changes until the application approves the exact proposed action.');
    const queued = this.queue.splice(0);
    queued.forEach(event => this.event(event));
    this.changed();
  }
  stop(waiting = false) {
    if (!this.active) return;
    this.clearWakeTimers();
    this.outputActive = false;
    this.speech = waiting ? 'waiting' : 'stopped';
    if (this.summary === 'requested') this.summary = 'canceled';
    this.handle?.setOutputMuted(true);
    this.commandCursor = this.commandText.length;
    // Announced delegations can precede response.created; retain the cancellation
    // even when the corresponding group only arrives after Resume.
    for (const [delegation, responseId] of this.delegations) {
      this.canceledDelegations.add(delegation);
      if (responseId) this.canceledResponses.add(responseId);
    }
    for (const group of this.groups.values()) {
      group.blocked = true;
      this.canceledDelegations.add(group.delegation);
      this.canceledResponses.add(group.responseId);
    }
    for (const call of this.calls.values()) {
      if (call.status === 'approval') this.reject(call.call_id, 'Canceled when Chatty was stopped. No change request was sent.');
      else if (call.status === 'running' && call.capability?.requires_approval) call.message = 'This change was already approved and may still complete. Check GitHub before requesting it again.';
    }
    this.busyDelegations.clear();
    this.instruction(waiting ? 'The addressed request is finished or its wake window expired. Stay silent and do not start tools until someone addresses you with Chatty again. Ordinary conversation is not a new request.' : 'Stop speaking now. Stay silent and do not start new tools until someone addresses you with Chatty again or clicks Resume. This supersedes earlier speaking requests.');
    this.changed();
  }
  resume() {
    if (!this.active || !this.handle) return;
    this.speech = 'listening';
    this.beginWake();
    this.handle.setInputEnabled(true);
    this.handle.setOutputMuted(false);
    this.instruction(this.source === 'meeting-tab' ? 'You have been addressed. Answer this one request, including final tool results, briefly. Then stay silent until someone addresses you with Chatty again. Do not answer unrelated conversation or resume canceled tool requests.' : 'The user has resumed the conversation. You may respond to the latest request and future speech. Keep answers brief. Do not resume a canceled tool request; ask for a new request when necessary.');
    this.changed();
  }
  summarize() {
    if (!this.active || !this.handle || !this.transcripts.length) return;
    this.resume();
    this.summary = 'requested';
    this.instruction('The user clicked Summarize. Immediately give a concise summary of this actual conversation: decisions, open questions, and action items with owners only when explicitly stated. Do not invent facts or create any tickets. Then pause and listen.', 'summary');
    this.changed();
  }
  end() {
    this.active = false;
    this.clearWakeTimers();
    this.abort.abort();
    this.queue = [];
    this.handle?.setOutputMuted(true);
    for (const call of this.calls.values()) {
      if (call.status === 'running') {
        call.status = call.capability?.requires_approval ? 'uncertain' : 'canceled';
        call.message = call.capability?.requires_approval ? 'Session ended during the change request. Check GitHub before retrying; the change may have completed.' : 'Session ended before the result arrived.';
      } else if (call.status === 'approval') {
        call.status = 'rejected';
        call.message = 'Session ended before approval. No request sent.';
      }
    }
    this.changed();
  }
  voiceCommand(delta) {
    this.commandText += delta;
    const commands = [];
    const patterns = [
      { kind: 'wake', re: /\bchatty\b/gi },
      { kind: 'stop', re: /\b(?:chatty[,\s]+(?:stop|pause|be quiet)|stop[,\s]+chatty)\b/gi },
    ];
    for (const { kind, re } of patterns) {
      for (const match of this.commandText.matchAll(re)) {
        const end = match.index + match[0].length;
        if (end > this.commandCursor) commands.push({ kind, end });
      }
    }
    commands.sort((a, b) => a.end - b.end || (a.kind === 'stop' ? 1 : -1));
    for (const command of commands) {
      if (command.kind === 'stop') this.stop();
      else if (this.speech !== 'listening') this.resume();
    }
    if (commands.length) this.commandCursor = commands.at(-1).end;
    if (this.commandText.length > 2000) {
      const trim = this.commandText.length - 300;
      this.commandText = this.commandText.slice(trim);
      this.commandCursor = Math.max(0, this.commandCursor - trim);
    }
  }
  event(envelope) {
    if (!this.active) return;
    if (!this.handle) { this.queue.push(envelope); return; }
    if (envelope.event_id) {
      if (this.events.has(envelope.event_id)) return;
      this.events.add(envelope.event_id);
    }
    const type = envelope.type;
    if (type === 'session.input_transcript.delta' || type === 'session.output_transcript.delta') {
      if (typeof envelope.delta !== 'string') return;
      const role = type === 'session.input_transcript.delta' ? 'participant' : 'chatty';
      this.transcripts.push({ role, delta: envelope.delta, start_ms: envelope.start_ms, end_ms: envelope.end_ms });
      if (role === 'participant') this.voiceCommand(envelope.delta);
      this.changed();
      return;
    }
    if (type === 'session.instructions.appended') {
      const purpose = this.pendingInstructions.get(envelope.client_event_id);
      this.pendingInstructions.delete(envelope.client_event_id);
      if (purpose === 'summary' && this.speech === 'listening' && this.summary === 'requested') {
        this.summary = 'accepted';
        this.send({ type: 'session.commentary.append', event_id: this.id('summary_prompt'), delegation_id: null, content: 'Begin the requested conversation summary now, following the instructions provided.' });
        this.changed();
      }
      return;
    }
    if (type === 'error') {
      this.onError(envelope.error?.message ?? envelope.message ?? 'Live rejected a command.');
      const id = envelope.client_event_id ?? envelope.error?.event_id;
      if (this.pendingInstructions.get(id) === 'summary') this.summary = 'error';
      this.pendingInstructions.delete(id);
      this.changed();
      return;
    }
    if (type === 'session.delegation.created' && envelope.target === 'responses') {
      const delegation = envelope.delegation_id ?? 'default';
      this.delegations.set(delegation, envelope.response_id ?? null);
      if (this.speech === 'listening' && !this.canceledDelegations.has(delegation)) this.busyDelegations.add(delegation);
      if (this.speech !== 'listening') this.canceledDelegations.add(delegation);
      if (this.canceledDelegations.has(delegation) && envelope.response_id) this.canceledResponses.add(envelope.response_id);
      return;
    }
    if (type !== 'response.event' || !envelope.event) return;
    const event = envelope.event;
    const delegation = envelope.delegation_id ?? 'default';
    if (event.type === 'response.created' && event.response?.id) {
      this.delegations.set(delegation, event.response.id);
      if (this.speech === 'listening' && !this.canceledDelegations.has(delegation)) this.busyDelegations.add(delegation);
    }
    const responseId = event.response?.id ?? event.response_id ?? this.delegations.get(delegation) ?? delegation;
    const key = `${delegation}:${responseId}`;
    const blocked = this.speech !== 'listening' || this.canceledDelegations.has(delegation) || this.canceledResponses.has(responseId);
    if (blocked) {
      this.canceledDelegations.add(delegation);
      this.canceledResponses.add(responseId);
    }
    if (!this.groups.has(key)) this.groups.set(key, { delegation, responseId, calls: new Set(), terminal: false, continued: false, blocked });
    const group = this.groups.get(key);
    group.blocked ||= blocked;
    if (group.blocked) this.busyDelegations.delete(delegation);
    if (event.type === 'response.output_item.done' && event.item?.type === 'function_call') this.functionCall(event.item, key);
    if (TERMINAL.has(event.type)) {
      group.terminal = true;
      if (event.type === 'response.failed' || event.type === 'response.cancelled' || event.type === 'response.incomplete') {
        group.blocked = true;
        this.onError(event.response?.error?.message ?? `Backend work ${event.type.slice(9)}.`);
      }
      if (group.blocked || !group.calls.size) this.busyDelegations.delete(delegation);
      this.continueGroup(key);
      this.scheduleQuiet();
    }
  }
  functionCall(item, key) {
    if (!item.call_id || this.calls.has(item.call_id)) return;
    const call = { call_id: item.call_id, name: item.name, capability: this.capabilities[item.name], key, status: 'pending', sent: false, arguments: {}, links: [] };
    this.calls.set(item.call_id, call);
    this.groups.get(key).calls.add(item.call_id);
    if (this.source === 'meeting-tab') {
      this.needsFinalOutput = true;
      if (this.speech === 'listening' && !this.groups.get(key).blocked) this.busyDelegations.add(this.groups.get(key).delegation);
    }
    try {
      call.arguments = JSON.parse(typeof item.arguments === 'string' ? item.arguments : JSON.stringify(item.arguments));
      if (!call.arguments || typeof call.arguments !== 'object' || Array.isArray(call.arguments)) throw new Error('Arguments must be an object.');
      // Approval belongs to the UI; never promote model-supplied values.
      delete call.arguments.approved;
      freezeArguments(call.arguments);
    } catch {
      this.finish(call, JSON.stringify({ ok: false, error: 'Invalid tool arguments.' }), 'error');
      return;
    }
    if (this.speech !== 'listening' || this.groups.get(key).blocked) {
      this.groups.get(key).blocked = true;
      this.finish(call, JSON.stringify({ ok: false, error: 'Chatty is waiting or stopped. Ask again after Hey Chatty or Resume.' }), 'rejected');
    } else if (!call.capability) {
      this.finish(call, JSON.stringify({ ok: false, error: 'Unknown tool capability. Start a new session after refreshing the app.' }), 'error');
    } else if (call.capability.requires_approval) {
      if (!Object.keys(call.arguments).length || (item.name === 'create_issue'
          && (typeof call.arguments.title !== 'string' || !call.arguments.title.trim() || typeof call.arguments.body !== 'string'))) {
        this.finish(call, JSON.stringify({ ok: false, error: 'Concrete change details are required for review.' }), 'error');
      } else {
        call.status = 'approval';
        this.changed();
      }
    } else this.run(call, false);
  }
  approve(id) {
    const call = this.calls.get(id);
    if (!this.active || this.speech !== 'listening' || call?.status !== 'approval' || this.groups.get(call.key)?.blocked) return;
    this.run(call, true);
  }
  reject(id, message = 'The user rejected this change. No change request was sent.') {
    const call = this.calls.get(id);
    if (!this.active || call?.status !== 'approval') return;
    this.finish(call, JSON.stringify({ ok: false, error: message }), 'rejected');
  }
  async run(call, approved) {
    call.status = 'running';
    this.changed();
    try {
      const result = await this.execute({ session_id: this.handle.sessionId, call_id: call.call_id, name: call.name, arguments: call.arguments, ...(approved ? { approved: true } : {}) }, this.abort.signal);
      if (!this.active) return;
      if (result.call_id !== call.call_id || typeof result.output !== 'string') throw new Error('Tool server returned an invalid result.');
      this.finish(call, result.output);
    } catch (error) {
      if (!this.active) return;
      this.finish(call, JSON.stringify({ ok: false, error: call.capability?.requires_approval ? `Result uncertain: ${error.message}. Check GitHub before retrying; the change may have completed.` : error.message }), call.capability?.requires_approval ? 'uncertain' : 'error');
    }
  }
  finish(call, output, status) {
    if (this.source === 'meeting-tab' && this.speech === 'listening') {
      this.lastToolResultAt = this.now();
      this.needsFinalOutput = true;
    }
    call.output = output;
    let parsed;
    try { parsed = JSON.parse(output); } catch { parsed = { text: output }; }
    call.result = parsed;
    call.links = githubLinks(parsed);
    call.status = status ?? (parsed.error?.uncertain ? 'uncertain' : parsed.ok === false || parsed.error ? 'error' : 'complete');
    call.message = typeof parsed.error === 'string' ? parsed.error : parsed.error?.message;
    call.sent = this.send({ type: 'response.item.create', event_id: this.id('tool_result'), item: { type: 'function_call_output', call_id: call.call_id, output } });
    this.continueGroup(call.key);
    this.changed();
  }
  continueGroup(key) {
    const group = this.groups.get(key);
    if (!this.active || this.speech !== 'listening' || group.blocked || !group.terminal || group.continued || !group.calls.size) return;
    if (![...group.calls].every(id => this.calls.get(id).sent)) return;
    group.continued = this.send({ type: 'response.create', event_id: this.id('continue') });
  }
}
