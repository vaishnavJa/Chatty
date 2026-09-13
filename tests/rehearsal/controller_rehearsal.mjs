// Offline contract driver. Every model utterance and function call below is
// SCRIPTED. It exercises production controller/HTTP contracts, not Live quality.
import assert from 'node:assert/strict';
import { DemoController } from '../../web/controller.js';
import { createMeetingContext } from '../../web/context.js';

const [base, scenario] = process.argv.slice(2);
assert.match(base ?? '', /^http:\/\/127\.0\.0\.1:\d+$/);
let checks = 0;
const check = (condition, message) => { assert.ok(condition, message); checks += 1; };
const flush = () => new Promise(resolve => setImmediate(resolve));

async function waitFor(predicate, label) {
  const until = Date.now() + 5000;
  while (!predicate()) {
    if (Date.now() >= until) throw new Error(`Timed out: ${label}`);
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

async function post(path, body) {
  const response = await fetch(base + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Origin: base },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.message ?? JSON.stringify(result)), { code: result.code, status: response.status });
  return result;
}

function clockFixture() {
  let timestamp = Date.now(), next = 0;
  const jobs = new Map();
  return {
    now: () => timestamp,
    timers: {
      setTimeout(callback, delay) { const id = ++next; jobs.set(id, { callback, at: timestamp + delay }); return id; },
      clearTimeout(id) { jobs.delete(id); },
    },
    tick(ms) {
      const until = timestamp + ms;
      let count = 0;
      while (true) {
        const due = [...jobs].filter(([, job]) => job.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        assert.ok(++count < 100, 'The controller timer loop must settle');
        timestamp = due[1].at;
        jobs.delete(due[0]);
        due[1].callback();
      }
      timestamp = until;
    },
  };
}

async function setup({ delayVoice = false } = {}) {
  const session = await post('/api/live/session', { sdp: 'offline-contract-rehearsal' });
  const sessionId = session.session.id;
  const capabilities = (await (await fetch(base + '/api/capabilities')).json()).tools;
  const clock = clockFixture();
  const sent = [], muted = [], inputs = [], errors = [], approvals = [], acknowledgments = [];
  let transcriptId = 0, audioMs = 1000, responseId = 0, heldResult = null, releaseHeld;
  const gate = new Promise(resolve => { releaseHeld = resolve; });
  const context = createMeetingContext({
    sessionId,
    fetchImpl: (path, options) => fetch(base + path, { ...options, headers: { ...options.headers, Origin: base } }),
    onError: error => errors.push(error),
  });
  const approval = async (action, body) => {
    const request = { action, body, result: null };
    approvals.push(request);
    const result = await post(`/api/approvals/${action}`, body);
    request.result = result;
    if (delayVoice && action === 'voice' && result.status === 'approved') {
      heldResult = result;
      await gate; // A deliberate delayed delivery AFTER the real server receipt.
    }
    return result;
  };
  const controller = new DemoController({
    source: 'meeting-tab', capabilities, timers: clock.timers, now: clock.now,
    execute: async body => { await context.flush(); return post('/api/tools/execute', body); },
    approval, onTranscript: event => context.add(event), onError: error => errors.push(error),
  });
  controller.attach({
    sessionId, send: event => sent.push(event),
    setInputEnabled: value => inputs.push(value), setOutputMuted: value => muted.push(value),
    acknowledgeStop: async () => { acknowledgments.push('Okay'); return { played: true }; },
    close() {},
  });
  const transcript = (role, delta) => {
    const event = { type: `session.${role}_transcript.delta`, event_id: `scripted-${++transcriptId}`, delta, start_ms: audioMs, end_ms: audioMs + 400 };
    audioMs += 2000;
    controller.event(event);
    return event;
  };
  const tool = (callId, name, args) => {
    const id = `response-${++responseId}`, delegation_id = `delegation-${responseId}`;
    const event = value => controller.event({ type: 'response.event', delegation_id, event: value });
    event({ type: 'response.created', response: { id } });
    const item = { type: 'function_call', call_id: callId, name, arguments: JSON.stringify(args) };
    event({ type: 'response.output_item.done', item });
    event({ type: 'response.output_item.done', item }); // Duplicate Live delivery.
    event({ type: 'response.completed', response: { id, output: [] } });
  };
  const speakPrompt = async (scriptedParaphrase = null) => {
    await waitFor(() => controller.confirmation?.stage === 'instruction', 'fresh approval prompt');
    const confirmation = controller.confirmation;
    controller.event({ type: 'session.instructions.appended', client_event_id: confirmation.instructionId });
    controller.outputActivity(true);
    transcript('output', scriptedParaphrase ?? confirmation.prompt);
    controller.outputActivity(false);
    clock.tick(500);
    await waitFor(() => confirmation.stage === 'armed', 'real server arms heard prompt');
    return confirmation;
  };
  const reply = phrase => {
    controller.inputActivity(true, { available: true, quietSince: null, quietMs: 0 });
    transcript('input', phrase);
    controller.inputActivity(false, { available: true, quietSince: clock.now(), quietMs: 0 });
    clock.tick(1000);
    controller.inputActivity(false, { available: true, quietSince: clock.now() - 1000, quietMs: 1000 });
    clock.tick(0);
  };
  const finish = async id => {
    await waitFor(() => controller.calls.get(id)?.sent, `receipt for ${id}`);
    return controller.calls.get(id);
  };
  return { sessionId, controller, context, sent, muted, inputs, errors, approvals, acknowledgments, transcript, tool, speakPrompt, reply, finish, clock, get heldResult() { return heldResult; }, releaseHeld };
}

async function groupDecision() {
  const f = await setup();
  try {
    f.transcript('input', 'Munir can take the login retry bug.');
    f.transcript('input', 'The reproduction is retrying after the session expires.');
    f.transcript('input', 'Correction: Karim will own it, not Munir.');
    f.transcript('output', 'SCRIPTED assistant text must not become participant evidence.');
    check(f.controller.speech === 'waiting' && f.sent.every(event => event.type !== 'response.create'), 'Quiet evidence collection must not start work');
    await f.context.flush();
    f.transcript('input', 'Chatty, use what we agreed to update issue 42.');
    f.tool('meeting-read', 'read_meeting_context', { limit: 20 });
    const contextCall = await f.finish('meeting-read');
    const context = contextCall.result;
    assert.equal(context.ok, true);
    const fragments = context.fragments;
    check(fragments.slice(0, 3).map(row => row.fragment_id).join(',') === 'meeting-1,meeting-2,meeting-3', 'Two statements and correction keep distinct source refs');
    check(fragments[2].delta === 'Correction: Karim will own it, not Munir.' && fragments[2].start_ms === 5000, 'Correction evidence is exact and timestamped');
    check(context.evidence_only && context.speaker_identity === 'unavailable_mixed_audio' && !context.coverage.complete_meeting, 'Evidence does not invent speakers or complete coverage');
    check(!fragments.some(row => row.delta.startsWith('SCRIPTED assistant')), 'Assistant output never becomes participant evidence');
    const other = await post('/api/live/session', { sdp: 'offline-contract-rehearsal' });
    const isolated = await post('/api/tools/execute', { session_id: other.session.id, call_id: 'isolated-read', name: 'read_meeting_context', arguments: {} });
    check(JSON.parse(isolated.output).fragments.length === 0, 'A second session cannot read the first meeting');
    f.tool('repository-read', 'get_issue', { issue_number: 42 });
    const repository = await f.finish('repository-read');
    check(repository.links.includes('https://github.com/vaishnavJa/Chatty/issues/42'), 'Repository read provides a verified source URL');

    // SCRIPTED model interpretation. This proves data and action contracts, not
    // whether a real model independently identifies the final group decision.
    const original = { issue_number: 42, title: 'Login retry bug', body: 'Reproduce with an expired session (meeting-2). Proposed owner corrected to Karim (meeting-3).', assignees: ['karimkohel'] };
    f.tool('draft-original', 'update_issue', original);
    const proposal = await f.speakPrompt();
    const originalToken = proposal.approvalId;
    f.reply('Who is assigned?');
    await waitFor(() => f.controller.confirmation?.stage === 'instruction', 'saved-draft answer');
    check(f.controller.confirmation.approvalId === originalToken && !f.controller.calls.get('draft-original').sent, 'A question retains the exact unexecuted proposal');
    check(f.controller.calls.get('draft-original').answer.includes('karimkohel'), 'Assignee answer comes from saved arguments');
    assert.deepEqual(f.controller.calls.get('draft-original').arguments, original);
    await f.speakPrompt();
    f.reply('Actually change the title to Handle expired login retries.');
    const oldCall = await f.finish('draft-original');
    check(oldCall.status === 'rejected' && oldCall.result.ok === false, 'An amendment terminates the old write without execution');
    const revisionReply = f.approvals.filter(row => row.action === 'voice').at(-1);
    assert.equal(revisionReply.result.status, 'revision_requested');

    const revised = { ...original, title: 'Handle expired login retries' };
    f.tool('draft-revised', 'update_issue', revised);
    const fresh = await f.speakPrompt();
    check(fresh.approvalId !== originalToken, 'The amended arguments require fresh approval');
    f.reply('You have my green light.'); // The HTTP classifier reply is a fixture.
    const completed = await f.finish('draft-revised');
    check(completed.status === 'complete' && completed.result.data.assignees[0] === 'karimkohel', 'Only amended action receives a successful receipt');
    const approvedReply = f.approvals.filter(row => row.action === 'voice').at(-1);
    const duplicate = await post('/api/approvals/voice', approvedReply.body);
    check(JSON.stringify(duplicate) === JSON.stringify(approvedReply.result), 'Redelivered approval returns the same receipt');
    const stale = await post('/api/approvals/voice', revisionReply.body);
    check(stale.status === 'revision_requested', 'Old approval evidence stays terminal after replacement');
    check(f.controller.speech === 'listening', 'Questions and requests continue without repeating the wake word');

    f.transcript('input', 'Chatty, stop.');
    await flush();
    check(f.controller.speech === 'stopped' && f.muted.at(-1) === true && f.inputs.every(Boolean) && f.acknowledgments.length === 1, 'Stop acknowledges once, mutes output and leaves input enabled');
    f.transcript('input', 'We will check the corrected issue tomorrow.');
    await f.context.flush();
    const afterStop = await post('/api/tools/execute', { session_id: f.sessionId, call_id: 'meeting-read', name: 'read_meeting_context', arguments: { limit: 20 } });
    check(JSON.parse(afterStop.output).fragments.at(-1).delta === 'We will check the corrected issue tomorrow.', 'Quiet listening retains new evidence and a repeated read refreshes it');
    check(f.errors.length === 0, f.errors.join('; '));
  } finally { await f.context.stop(); }
}

async function permissionFailure() {
  const f = await setup();
  try {
    f.transcript('input', 'Chatty, create an issue about the permission failure.');
    const draft = { title: 'Permission failure rehearsal', body: 'Keep this draft if access is denied.' };
    f.tool('denied-create', 'create_issue', draft);
    await f.speakPrompt();
    f.reply('Sure, go ahead.');
    const call = await f.finish('denied-create');
    check(call.status === 'error' && call.result.error.code === 'permission_denied', 'A rejected GitHub request is never success');
    check(call.message.includes('permissions') && call.links.length === 0, 'The failure gives recovery guidance without a fabricated receipt link');
    check(JSON.stringify(call.arguments) === JSON.stringify(draft), 'The useful draft remains available after failure');
    const voice = f.approvals.filter(row => row.action === 'voice').at(-1);
    assert.deepEqual(await post('/api/approvals/voice', voice.body), voice.result);
    check(f.controller.speech === 'listening' && f.sent.filter(event => event.type === 'response.item.create').length === 1, 'Failure is delivered once and conversation remains active');
  } finally { await f.context.stop(); }
}

async function delayedResult() {
  const f = await setup({ delayVoice: true });
  try {
    f.transcript('input', 'Chatty, create the login retry issue.');
    f.tool('delayed-create', 'create_issue', { title: 'Login retry bug', body: 'Retry after an expired session fails.' });
    await f.speakPrompt('I can file the login retry problem we discussed. Shall I go ahead?');
    f.reply('Yeah, absolutely.');
    await waitFor(() => f.heldResult, 'provider completed but delivery is held');
    check(f.controller.calls.get('delayed-create').status === 'running', 'A pending delivery stays visibly in progress');
    f.transcript('input', 'Chatty, stop.');
    const continuations = f.sent.filter(event => event.type === 'response.create').length;
    check(f.controller.speech === 'stopped' && f.controller.calls.get('delayed-create').message.includes('may still complete'), 'Stop cannot claim an executing write was undone');
    f.releaseHeld();
    const call = await f.finish('delayed-create');
    check(call.status === 'complete' && call.links.length === 1, 'A late successful receipt remains visible');
    check(f.sent.filter(event => event.type === 'response.create').length === continuations && f.muted.at(-1) === true, 'The late result cannot resume speech after Stop');
    check(f.inputs.every(Boolean) && f.acknowledgments.length === 1, 'Stop still listens and acknowledges only once');
    const voice = f.approvals.filter(row => row.action === 'voice').at(-1);
    assert.deepEqual(await post('/api/approvals/voice', voice.body), voice.result);
    check(f.controller.speech === 'stopped', 'Replay does not reawaken the controller');
  } finally { f.releaseHeld(); await f.context.stop(); }
}

const scenarios = { 'group-decision': groupDecision, 'permission-failure': permissionFailure, 'delayed-result': delayedResult };
assert.ok(scenarios[scenario], 'Unknown offline rehearsal');
await scenarios[scenario]();
process.stdout.write(JSON.stringify({ mode: 'scripted-provider-contract-rehearsal', scenario, checks }));
