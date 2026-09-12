import test from 'node:test';
import assert from 'node:assert/strict';
import { DemoController, githubLinks } from '../../web/controller.js';

const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture({ source = 'microphone', execute, approval, capabilities, timers, now, tick, attach = true } = {}) {
  const clock = timers ? { timers, now, tick } : clockFixture();
  const sent = [], muted = [], inputs = [], requests = [], errors = [], approvalRequests = [];
  const proposals = new Map();
  const executeRequest = execute ?? (async body => {
    requests.push(body);
    return { call_id: body.call_id, output: JSON.stringify({ ok: true, data: { url: 'https://github.com/vaishnavJa/Chatty/issues/42' } }) };
  });
  const approvalRequest = approval ?? (async (action, body) => {
    approvalRequests.push({ action, ...body });
    if (action === 'prepare') {
      const approval_id = `approval_${body.call_id}`;
      proposals.set(approval_id, body);
      return { approval_id, call_id: body.call_id, prompt: `Proposed ${body.name}: ${JSON.stringify(body.arguments)}. Do you approve this change?`, expires_at: clock.now() + 60000 };
    }
    if (action === 'arm') return { armed: true };
    if (action === 'cancel') return { status: 'rejected' };
    const text = body.input_events.map(event => event.delta).join('').toLowerCase().replace(/[.,!?]/g, '').trim();
    if (!['yes', 'yes please', 'yes do it', 'confirm', 'chatty confirm', 'go ahead'].includes(text)) return { status: ['no', 'cancel', 'chatty stop'].includes(text) ? 'rejected' : 'ambiguous', receipt: { call_id: proposals.get(body.approval_id).call_id, output: JSON.stringify({ ok: false, error: 'The spoken response did not approve this change.' }) } };
    return { status: 'approved', receipt: await executeRequest(proposals.get(body.approval_id)) };
  });
  const handle = { sessionId: 'live_test', send: event => sent.push(event), setOutputMuted: value => muted.push(value), setInputEnabled: value => inputs.push(value), close() {} };
  const controller = new DemoController({ source, timers: clock.timers, now: clock.now, ...(capabilities !== undefined ? { capabilities } : {}), onError: error => errors.push(error), execute: executeRequest, approval: approvalRequest });
  if (attach) controller.attach(handle);
  const nested = (event, delegation_id = 'delegation_a') => controller.event({ type: 'response.event', delegation_id, event });
  const created = (id = 'response_a') => nested({ type: 'response.created', response: { id } });
  const call = (id = 'call_a', name = 'list_recent_commits', args = { limit: 3 }) => nested({ type: 'response.output_item.done', item: { type: 'function_call', call_id: id, name, arguments: JSON.stringify(args) } });
  const completed = (id = 'response_a') => nested({ type: 'response.completed', response: { id, output: [] } });
  return { controller, sent, muted, inputs, requests, errors, approvalRequests, handle, nested, created, call, completed, clock };
}
const continuations = f => f.sent.filter(event => event.type === 'response.create');
const results = f => f.sent.filter(event => event.type === 'response.item.create');
let transcriptSequence = 0;
function transcript(f, role, delta, start = 10000) {
  const event = { type: `session.${role}_transcript.delta`, event_id: `transcript_${++transcriptSequence}`, delta, start_ms: start, end_ms: start + 100 };
  f.controller.event(event);
  return event;
}
async function spokenPrompt(f) {
  await flush();
  const confirmation = f.controller.confirmation;
  if (!confirmation || confirmation.stage !== 'instruction') return;
  f.controller.event({ type: 'session.instructions.appended', client_event_id: confirmation.instructionId });
  f.controller.outputActivity(true);
  transcript(f, 'output', confirmation.prompt, 1000 + transcriptSequence * 100);
  f.controller.outputActivity(false);
  f.clock.tick(500);
  await flush();
}
function participantReply(f, phrase = 'yes', quiet = 1000) {
  f.controller.inputActivity(true, { available: true, quietSince: null, quietMs: 0 });
  const event = transcript(f, 'input', phrase, Math.max(10000, (f.controller.confirmation?.outputEndMs ?? 0) + 100));
  f.controller.inputActivity(false, { available: true, quietSince: f.clock.now(), quietMs: 0 });
  f.clock.tick(quiet);
  f.controller.inputActivity(false, { available: true, quietSince: f.clock.now() - quiet, quietMs: quiet });
  f.clock.tick(0);
  return event;
}
async function voiceApprove(f, phrase = 'yes') {
  await spokenPrompt(f);
  if (f.controller.confirmation?.stage !== 'armed') return;
  participantReply(f, phrase);
  await flush();
}

test('microphone starts unmuted and meeting starts wake-gated with input on', () => {
  const mic = fixture(), meeting = fixture({ source: 'meeting-tab' });
  assert.deepEqual(mic.muted, [false]);
  assert.deepEqual(meeting.muted, [true]);
  assert.deepEqual(meeting.inputs, [true]);
  assert.match(mic.sent[0].content, /wake word is not required/);
  assert.equal(mic.sent[0].delegation_id, null);
});

test('events arriving before the handle resolves are processed once after attach', async () => {
  const f = fixture({ attach: false });
  f.created(); f.call(); f.completed();
  assert.equal(f.requests.length, 0);
  f.controller.attach(f.handle);
  await flush();
  assert.equal(f.requests.length, 1);
  assert.equal(continuations(f).length, 1);
});

test('dispatch requires a nested completed function item, not arguments or unwrapped events', async () => {
  const f = fixture();
  f.controller.event({ type: 'response.output_item.done', item: { type: 'function_call', name: 'list_recent_commits', call_id: 'bad' } });
  f.nested({ type: 'response.function_call_arguments.done', arguments: '{}' });
  await flush();
  assert.equal(f.requests.length, 0);
});

test('duplicate completed calls execute once and send one continuation', async () => {
  const f = fixture();
  f.created(); f.call(); f.call(); f.completed(); f.completed();
  await flush();
  assert.equal(f.requests.length, 1);
  assert.equal(results(f).length, 1);
  assert.equal(continuations(f).length, 1);
});

test('parallel function results wait for all calls and the terminal response snapshot', async () => {
  const pending = new Map();
  const f = fixture({ execute: body => new Promise(resolve => pending.set(body.call_id, resolve)) });
  f.created(); f.call('a'); f.call('b');
  pending.get('a')({ call_id: 'a', output: '{"ok":true}' });
  await flush();
  assert.equal(results(f).length, 1);
  assert.equal(continuations(f).length, 0);
  f.completed();
  assert.equal(continuations(f).length, 0);
  pending.get('b')({ call_id: 'b', output: '{"ok":true}' });
  await flush();
  assert.equal(results(f).length, 2);
  assert.equal(continuations(f).length, 1);
});

test('empty terminal output does not erase a pending issue approval', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Meeting summary', body: 'Capture decisions.', approved: true }); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('write').status, 'approval');
  assert.equal(continuations(f).length, 0);
  await voiceApprove(f); await voiceApprove(f);
  await flush();
  assert.equal(f.requests.length, 1);
  assert.equal('approved' in f.requests[0], false);
  assert.equal('approved' in f.requests[0].arguments, false);
  assert.equal(continuations(f).length, 1);
});

test('rejecting an issue sends an error output without touching GitHub', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Example', body: 'Example body' }); f.completed();
  f.controller.reject('write');
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(JSON.parse(results(f)[0].item.output).ok, false);
  assert.equal(continuations(f).length, 1);
});

test('stop immediately mutes, leaves input on, and ignores old wake words', () => {
  const f = fixture({ source: 'meeting-tab' });
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'Hey Chat' });
  assert.equal(f.controller.speech, 'waiting');
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'ty, what changed?' });
  assert.equal(f.controller.speech, 'listening');
  f.controller.stop();
  f.controller.event({ type: 'session.input_transcript.delta', delta: ' Please wait.' });
  assert.equal(f.controller.speech, 'stopped');
  assert.equal(f.muted.at(-1), true);
  assert.equal(f.inputs.at(-1), true);
  f.controller.event({ type: 'session.input_transcript.delta', delta: ' Hey Chatty, continue.' });
  assert.equal(f.controller.speech, 'listening');
  assert.equal(f.muted.at(-1), false);
});

test('a stop phrase spanning fragments wins over an earlier wake phrase', () => {
  const f = fixture({ source: 'meeting-tab' });
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'Hey Chatty, hello. Chatty,' });
  f.controller.event({ type: 'session.input_transcript.delta', delta: ' stop.' });
  assert.equal(f.controller.speech, 'stopped');
});

test('stop rejects pending issue approval and prevents old backend work from continuing', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Example', body: 'Details' }); f.completed();
  f.controller.stop(); await voiceApprove(f); f.controller.resume();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('write').status, 'rejected');
  assert.equal(continuations(f).length, 0);
});

test('waiting meeting mode does not execute tools even if Live requests one', async () => {
  const f = fixture({ source: 'meeting-tab' });
  f.created(); f.call(); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(continuations(f).length, 0);
});

test('ending while a write runs records uncertainty and discards late result commands', async () => {
  let resolve;
  const f = fixture({ execute: () => new Promise(done => { resolve = done; }) });
  f.created(); f.call('write', 'create_issue', { title: 'Example', body: 'Details' }); f.completed(); await voiceApprove(f);
  f.controller.end();
  resolve({ call_id: 'write', output: '{"ok":true}' });
  await flush();
  assert.equal(f.controller.calls.get('write').status, 'uncertain');
  assert.equal(results(f).length, 0);
  assert.equal(continuations(f).length, 0);
});

test('read errors and uncertain writes are visible and returned to the backend', async () => {
  const f = fixture({ execute: async () => { throw new Error('Connection lost'); } });
  f.created(); f.call('read'); f.call('write', 'create_issue', { title: 'Example', body: 'Details' }); f.completed(); await voiceApprove(f);
  await flush();
  assert.equal(f.controller.calls.get('read').status, 'error');
  assert.equal(f.controller.calls.get('write').status, 'uncertain');
  assert.match(f.controller.calls.get('write').message, /Check GitHub before retrying/);
  assert.equal(continuations(f).length, 1);
});

test('transcript fragments preserve exact spaces, timestamps, overlap and event dedupe', () => {
  const f = fixture();
  const event = { type: 'session.input_transcript.delta', event_id: 'caption_a', delta: 'What ', start_ms: 100, end_ms: 200 };
  f.controller.event(event); f.controller.event(event);
  f.controller.event({ type: 'session.output_transcript.delta', delta: 'Yes', start_ms: 150, end_ms: 200 });
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'changed?', start_ms: 200, end_ms: 350 });
  assert.equal(f.controller.transcripts.length, 3);
  assert.equal(f.controller.transcripts.filter(row => row.role === 'participant').map(row => row.delta).join(''), 'What changed?');
  assert.equal(f.controller.transcripts[1].start_ms, 150);
});

test('summary follows the accepted instruction and never treats backend completion as speech', () => {
  const f = fixture();
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'We decided to test audio.' });
  f.controller.summarize();
  const instruction = f.sent.find(event => event.event_id?.startsWith('chatty_summary_'));
  assert.equal(f.controller.summary, 'requested');
  assert.equal(f.sent.filter(event => event.type === 'session.commentary.append').length, 0);
  f.controller.event({ type: 'session.instructions.appended', client_event_id: instruction.event_id });
  assert.equal(f.controller.summary, 'accepted');
  assert.equal(f.sent.filter(event => event.type === 'session.commentary.append').length, 1);
  f.created(); f.completed();
  assert.equal(f.controller.summary, 'accepted');
});

test('receipt links accept only HTTPS github.com and never render hostile URLs', () => {
  assert.deepEqual(githubLinks({ url: 'https://github.com/vaishnavJa/Chatty/issues/42', duplicate: 'https://github.com/vaishnavJa/Chatty/issues/42', hostile: ['javascript:alert(1)', 'https://github.com.evil.test/path', 'https://github.com@evil.test/path', 'http://github.com/x/y', '<img src=x onerror=alert(1)>'] }), ['https://github.com/vaishnavJa/Chatty/issues/42']);
});

test('a second delegated backend response can continue independently', async () => {
  const f = fixture();
  f.created(); f.call('first'); f.completed();
  await flush();
  f.created('response_b'); f.call('second'); f.completed('response_b');
  await flush();
  assert.equal(continuations(f).length, 2);
});

test('invalid issue payload never reaches a write or approval control', async () => {
  const f = fixture(); f.created(); f.call('write', 'create_issue', { title: ' ', body: 'Details' }); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('write').status, 'error');
});

test('late calls from a stopped response stay blocked after Resume', async () => {
  const f = fixture(); f.created(); f.controller.stop(); f.controller.resume(); f.call('late'); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(continuations(f).length, 0);
});

test('summary acknowledgment arriving after Stop cannot trigger more speech', () => {
  const f = fixture();
  f.controller.event({ type: 'session.input_transcript.delta', delta: 'We decided to test.' });
  f.controller.summarize();
  const instruction = f.sent.find(event => event.event_id?.startsWith('chatty_summary_'));
  f.controller.stop();
  f.controller.event({ type: 'session.instructions.appended', client_event_id: instruction.event_id });
  assert.equal(f.controller.summary, 'canceled');
  assert.equal(f.sent.filter(event => event.type === 'session.commentary.append').length, 0);
});

test('structured uncertain GitHub errors remain uncertain in the UI', async () => {
  const f = fixture({ execute: async body => ({ call_id: body.call_id, output: '{"ok":false,"error":{"code":"call_pending","message":"Do not retry this write.","uncertain":true}}' }) });
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Details' }); f.completed(); await voiceApprove(f);
  await flush();
  assert.equal(f.controller.calls.get('write').status, 'uncertain');
  assert.equal(f.controller.calls.get('write').message, 'Do not retry this write.');
});

test('Stop cancels an announced delegation before its first response group exists', async () => {
  const f = fixture();
  f.controller.event({ type: 'session.delegation.created', target: 'responses', delegation_id: 'delegation_a', response_id: 'response_a' });
  assert.equal(f.controller.groups.size, 0);
  f.controller.stop();
  f.controller.resume();
  f.created();
  f.call('late_read');
  f.call('late_write', 'create_issue', { title: 'Stale issue', body: 'Do not execute.' });
  f.completed();
  await voiceApprove(f);
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('late_read').status, 'rejected');
  assert.equal(f.controller.calls.get('late_write').status, 'rejected');
  assert.equal(continuations(f).length, 0);
});

test('a canceled delegation stays canceled when its response ID was not yet announced', async () => {
  const f = fixture();
  f.controller.event({ type: 'session.delegation.created', target: 'responses', delegation_id: 'delegation_a' });
  f.controller.stop(); f.controller.resume();
  f.created(); f.call('late'); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(continuations(f).length, 0);
});

test('known canceled response IDs block delayed events without their original delegation ID', async () => {
  const f = fixture();
  f.controller.event({ type: 'session.delegation.created', target: 'responses', delegation_id: 'delegation_a', response_id: 'response_a' });
  f.controller.stop(); f.controller.resume();
  const delayed = event => f.controller.event({ type: 'response.event', event });
  delayed({ type: 'response.created', response: { id: 'response_a' } });
  delayed({ type: 'response.output_item.done', item: { type: 'function_call', name: 'list_recent_commits', call_id: 'late', arguments: '{}' } });
  delayed({ type: 'response.completed', response: { id: 'response_a', output: [] } });
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(continuations(f).length, 0);
});

test('a fresh delegation after Resume may execute independently of canceled work', async () => {
  const f = fixture();
  f.controller.event({ type: 'session.delegation.created', target: 'responses', delegation_id: 'old', response_id: 'old_response' });
  f.controller.stop(); f.controller.resume();
  f.controller.event({ type: 'session.delegation.created', target: 'responses', delegation_id: 'delegation_a', response_id: 'response_a' });
  f.created(); f.call('fresh'); f.completed();
  await flush();
  assert.equal(f.requests.length, 1);
  assert.equal(continuations(f).length, 1);
});

const expandedCapabilities = {
  update_issue: { label: 'Edit GitHub issue', requires_approval: true, destructive: false },
  update_project_item: { label: 'Update project item', requires_approval: true, destructive: false },
  delete_repository_file: { label: 'Delete repository file', requires_approval: true, destructive: true },
  get_issue: { label: 'Read issue', requires_approval: false, destructive: false },
};
const changes = [
  ['update_issue', { issue_number: 8, title: 'Revised title', body: 'Exact public content', labels: ['demo'] }],
  ['update_project_item', { item_id: 'item-demo', field_name: 'Status', value: 'In progress' }],
  ['delete_repository_file', { path: 'obsolete.md', branch: 'codex/demo', expected_sha: 'a'.repeat(40), message: 'Remove obsolete guide' }],
];

for (const [name, args] of changes) {
  test(`${name} requires an exact spoken proposal and approval and executes once`, async () => {
    const f = fixture({ capabilities: expandedCapabilities });
    f.created(); f.call('change', name, { ...args, approved: true }); f.completed();
    await flush();
    assert.equal(f.requests.length, 0);
    const proposed = f.controller.calls.get('change');
    assert.equal(proposed.status, 'approval');
    assert.equal(proposed.capability.label, expandedCapabilities[name].label);
    assert.equal(proposed.capability.destructive, expandedCapabilities[name].destructive);
    assert.deepEqual(proposed.arguments, args);
    assert.ok(Object.isFrozen(proposed.arguments));
    assert.throws(() => { proposed.arguments.title = 'Different'; }, TypeError);
    if (proposed.arguments.labels) assert.throws(() => proposed.arguments.labels.push('unreviewed'), TypeError);
    await voiceApprove(f); await voiceApprove(f);
    await flush();
    assert.equal(f.requests.length, 1);
    assert.equal('approved' in f.requests[0], false);
    assert.deepEqual(f.requests[0].arguments, args);
    assert.equal(continuations(f).length, 1);
  });

  test(`Stop and End each prevent late ${name} approval`, async () => {
    for (const end of [false, true]) {
      const f = fixture({ capabilities: expandedCapabilities });
      f.created(); f.call('change', name, args); f.completed();
      if (end) f.controller.end();
      else { f.controller.stop(); f.controller.resume(); }
      await voiceApprove(f);
      await flush();
      assert.equal(f.requests.length, 0);
      assert.equal(f.controller.calls.get('change').status, 'rejected');
      assert.equal(continuations(f).length, 0);
    }
  });

  test(`ending during ${name} keeps an uncertain receipt and ignores late completion`, async () => {
    let resolve;
    const f = fixture({ capabilities: expandedCapabilities, execute: () => new Promise(done => { resolve = done; }) });
    f.created(); f.call('change', name, args); f.completed(); await voiceApprove(f);
    f.controller.end();
    resolve({ call_id: 'change', output: '{"ok":true}' });
    await flush();
    assert.equal(f.controller.calls.get('change').status, 'uncertain');
    assert.match(f.controller.calls.get('change').message, /change may have completed/);
    assert.equal(results(f).length, 0);
    assert.equal(continuations(f).length, 0);
  });
}

test('unknown tools fail closed even when the model supplies approval', async () => {
  const f = fixture({ capabilities: expandedCapabilities });
  f.created(); f.call('unknown', 'unregistered_operation', { approved: true, target: 'repo' }); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('unknown').status, 'error');
  assert.match(f.controller.calls.get('unknown').message, /Unknown tool capability/);
});

test('explicit capability manifests do not silently inherit legacy tool permission', async () => {
  const f = fixture({ capabilities: expandedCapabilities });
  f.created(); f.call('legacy', 'create_issue', { title: 'Unregistered', body: 'No inherited permission.' }); f.completed();
  await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('legacy').status, 'error');
});

test('declared reads run directly with no approval field', async () => {
  const f = fixture({ capabilities: expandedCapabilities });
  f.created(); f.call('read', 'get_issue', { issue_number: 8 }); f.completed();
  await flush();
  assert.equal(f.requests.length, 1);
  assert.equal('approved' in f.requests[0], false);
  assert.equal(f.controller.calls.get('read').status, 'complete');
});

test('malformed or contradictory capability metadata cannot start a controller', () => {
  for (const capabilities of [null, [], { update_issue: { label: 'Edit', requires_approval: 'true', destructive: false } }, { delete_repository_file: { label: 'Delete', requires_approval: false, destructive: true } }]) {
    assert.throws(() => fixture({ capabilities }), /capabilities/);
  }
});

test('a stopped in-flight project write can confirm but cannot restart backend work', async () => {
  let resolve;
  const f = fixture({ capabilities: expandedCapabilities, execute: () => new Promise(done => { resolve = done; }) });
  f.created(); f.call('change', 'update_project_item', changes[1][1]); f.completed(); await voiceApprove(f);
  f.controller.stop();
  assert.match(f.controller.calls.get('change').message, /already being processed/);
  resolve({ call_id: 'change', output: '{"ok":true}' });
  await flush();
  assert.equal(f.controller.calls.get('change').status, 'complete');
  assert.equal(continuations(f).length, 0);
});

test('failed edit remains uncertain with no automatic retry', async () => {
  let count = 0;
  const f = fixture({ capabilities: expandedCapabilities, execute: async () => { ++count; throw new Error('Connection lost'); } });
  f.created(); f.call('change', 'update_issue', changes[0][1]); f.completed(); await voiceApprove(f);
  await flush();
  await voiceApprove(f); f.call('change', 'update_issue', changes[0][1]);
  await flush();
  assert.equal(count, 1);
  assert.equal(f.controller.calls.get('change').status, 'uncertain');
  assert.match(f.controller.calls.get('change').message, /change may have completed/);
});

function clockFixture() {
  let timestamp = 0, next = 0;
  const jobs = new Map();
  return {
    now: () => timestamp,
    timers: {
      setTimeout(callback, delay) { const id = ++next; jobs.set(id, { callback, at: timestamp + delay }); return id; },
      clearTimeout(id) { jobs.delete(id); },
    },
    tick(ms) {
      const until = timestamp + ms;
      while (true) {
        const due = [...jobs].filter(([, job]) => job.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timestamp = due[1].at;
        jobs.delete(due[0]);
        due[1].callback();
      }
      timestamp = until;
    },
  };
}

const speak = (f, delta) => f.controller.event({ type: 'session.input_transcript.delta', delta });

test('the bare token Chatty wakes, and Chatty stop wins over that wake', () => {
  const f = fixture({ source: 'meeting-tab' });
  speak(f, 'Chat');
  assert.equal(f.controller.speech, 'waiting');
  speak(f, 'ty, what changed?');
  assert.equal(f.controller.speech, 'listening');
  speak(f, ' Chatty, stop.');
  assert.equal(f.controller.speech, 'stopped');
  speak(f, ' Stop Chatty.');
  assert.equal(f.controller.speech, 'stopped');
  speak(f, ' Chatty, show the issue.');
  assert.equal(f.controller.speech, 'listening');
});

test('meeting returns quiet after one audible answer and ignores ordinary speech', async () => {
  const clock = clockFixture();
  const f = fixture({ source: 'meeting-tab', ...clock });
  speak(f, 'Chatty, hello.');
  f.controller.outputActivity(true);
  clock.tick(500);
  f.controller.outputActivity(false);
  clock.tick(1499);
  assert.equal(f.controller.speech, 'listening');
  clock.tick(1);
  assert.equal(f.controller.speech, 'waiting');
  assert.equal(f.muted.at(-1), true);
  speak(f, ' Now what should we do next?');
  f.created(); f.call('ordinary'); f.completed();
  await flush();
  assert.equal(f.controller.speech, 'waiting');
  assert.equal(f.requests.length, 0);
  speak(f, ' Chatty, another question.');
  assert.equal(f.controller.speech, 'listening');
});

test('interim checking speech and tool completion cannot cut off the final answer', async () => {
  const clock = clockFixture();
  let resolve;
  const f = fixture({ source: 'meeting-tab', ...clock, execute: () => new Promise(done => { resolve = done; }) });
  speak(f, 'Chatty, list the commits.');
  f.created(); f.call('read'); f.completed();
  f.controller.outputActivity(true);
  f.controller.outputActivity(false);
  clock.tick(2000);
  assert.equal(f.controller.speech, 'listening');
  resolve({ call_id: 'read', output: '{"ok":true}' });
  await flush();
  clock.tick(2000);
  assert.equal(f.controller.speech, 'listening');
  f.created('final_response'); f.completed('final_response');
  clock.tick(2000);
  assert.equal(f.controller.speech, 'listening');
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  clock.tick(1500);
  assert.equal(f.controller.speech, 'waiting');
});

test('an utterance already playing when a tool resolves does not count as final output', async () => {
  const clock = clockFixture();
  let resolve;
  const f = fixture({ source: 'meeting-tab', ...clock, execute: () => new Promise(done => { resolve = done; }) });
  speak(f, 'Chatty, check the repo.');
  f.created(); f.call('read'); f.completed();
  f.controller.outputActivity(true);
  resolve({ call_id: 'read', output: '{"ok":true}' });
  await flush();
  f.created('final_response'); f.completed('final_response');
  f.controller.outputActivity(false);
  clock.tick(2000);
  assert.equal(f.controller.speech, 'listening');
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  clock.tick(1500);
  assert.equal(f.controller.speech, 'waiting');
});

test('the bounded wake lease mutes even when output activity is unavailable', () => {
  const clock = clockFixture();
  const f = fixture({ source: 'meeting-tab', ...clock });
  speak(f, 'Chatty, hello.');
  clock.tick(89999);
  assert.equal(f.controller.speech, 'listening');
  clock.tick(1);
  assert.equal(f.controller.speech, 'waiting');
});

test('microphone conversation stays active across output silence', () => {
  const clock = clockFixture();
  const f = fixture({ ...clock });
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  clock.tick(100000);
  assert.equal(f.controller.speech, 'listening');
});

test('old silence timers cannot close a newly resumed request', () => {
  const clock = clockFixture();
  const f = fixture({ source: 'meeting-tab', ...clock });
  speak(f, 'Chatty, hello.');
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  clock.tick(1000);
  f.controller.stop();
  speak(f, ' Chatty, start again.');
  clock.tick(1000);
  assert.equal(f.controller.speech, 'listening');
  f.controller.end();
  clock.tick(100000);
  assert.equal(f.controller.active, false);
});

test('voice approval succeeds without a browser approval API or approving tool argument', async () => {
  const f = fixture();
  assert.equal(f.controller.approve, undefined);
  f.created(); f.call('voice_only', 'create_issue', { title: 'Voice only', body: 'Approved in the meeting.', approved: true }); f.completed();
  await voiceApprove(f, 'yes please');
  assert.equal(f.requests.length, 1);
  assert.deepEqual(f.approvalRequests.map(request => request.action), ['prepare', 'arm', 'voice']);
  assert.equal('approved' in f.requests[0], false);
  assert.equal('approved' in f.requests[0].arguments, false);
  assert.equal(results(f).length, 1);
  assert.equal(continuations(f).length, 1);
});

test('instruction acknowledgment alone and preexisting output cannot arm approval', async () => {
  const f = fixture();
  f.controller.outputActivity(true);
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await flush();
  const confirmation = f.controller.confirmation;
  f.controller.event({ type: 'session.instructions.appended', client_event_id: confirmation.instructionId });
  transcript(f, 'output', confirmation.prompt);
  f.controller.outputActivity(false);
  f.clock.tick(5000); await flush();
  assert.equal(f.approvalRequests.filter(request => request.action === 'arm').length, 0);
  assert.equal(f.requests.length, 0);
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  f.clock.tick(500); await flush();
  assert.equal(f.controller.confirmation.stage, 'prompting');
  transcript(f, 'output', confirmation.prompt, 11000);
  f.clock.tick(500); await flush();
  assert.equal(f.controller.confirmation.stage, 'armed');
});

test('earlier yes and Chatty output yes never approve a pending change', async () => {
  const f = fixture();
  transcript(f, 'input', 'yes', 100);
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  transcript(f, 'output', 'Yes, I can do that.', 50000);
  f.controller.inputActivity(false, { available: true, quietSince: 100, quietMs: 10000 });
  f.clock.tick(10000); await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.approvalRequests.filter(request => request.action === 'voice').length, 0);
});

test('transcript yes without a genuine post-prompt input activity cycle cannot approve', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  transcript(f, 'input', 'yes', 100000);
  f.controller.inputActivity(false, { available: true, quietSince: null, quietMs: 0 });
  f.clock.tick(10000); await flush();
  assert.equal(f.requests.length, 0);
});

test('partial yes followed by no is submitted as one unapproved utterance', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  f.controller.inputActivity(true, { available: true, quietSince: null, quietMs: 0 });
  transcript(f, 'input', 'yes', 100000);
  f.controller.inputActivity(false, { available: true, quietSince: 1, quietMs: 0 });
  f.clock.tick(800);
  f.controller.inputActivity(false, { available: true, quietSince: null, quietMs: 0 });
  f.clock.tick(300);
  assert.equal(f.requests.length, 0);
  f.controller.inputActivity(true, { available: true, quietSince: null, quietMs: 0 });
  transcript(f, 'input', ', no, wait', 100100);
  f.controller.inputActivity(false, { available: true, quietSince: 1100, quietMs: 0 });
  f.clock.tick(1000);
  f.controller.inputActivity(false, { available: true, quietSince: 1100, quietMs: 1000 });
  f.clock.tick(0); await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.calls.get('write').status, 'rejected');
  assert.equal(f.approvalRequests.find(request => request.action === 'voice').input_events.map(event => event.delta).join(''), 'yes, no, wait');
  assert.equal(continuations(f).length, 1);
});

for (const phrase of ['no', 'cancel', 'yes but change the title']) {
  test(`spoken ${JSON.stringify(phrase)} ends the proposal without executing it or retrying`, async () => {
    const f = fixture();
    f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
    await voiceApprove(f, phrase);
    f.clock.tick(10000); await flush();
    assert.equal(f.requests.length, 0);
    assert.equal(f.controller.calls.get('write').status, 'rejected');
    assert.equal(results(f).length, 1);
    assert.equal(continuations(f).length, 1);
    assert.equal(f.approvalRequests.filter(request => request.action === 'prepare').length, 1);
  });
}

test('queued mutations each need their own readback and fresh spoken approval', async () => {
  const f = fixture();
  f.created();
  f.call('one', 'create_issue', { title: 'One', body: 'First exact action' });
  f.call('two', 'create_issue', { title: 'Two', body: 'Second exact action' });
  f.completed();
  await voiceApprove(f);
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].call_id, 'one');
  assert.equal(f.controller.confirmation.call.call_id, 'two');
  assert.equal(continuations(f).length, 0);
  f.clock.tick(1000);
  assert.equal(f.requests.length, 1);
  await voiceApprove(f, 'go ahead');
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1].call_id, 'two');
  assert.equal(results(f).length, 2);
  assert.equal(continuations(f).length, 1);
});

test('duplicate input evidence and duplicate changed arguments never authorize a second write', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Original', body: 'Original body' }); f.completed();
  await spokenPrompt(f);
  const event = participantReply(f);
  f.controller.event(event);
  f.call('write', 'create_issue', { title: 'Injected', body: 'Different body', approved: true });
  await flush();
  f.controller.event(event); f.completed();
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].arguments.title, 'Original');
  assert.equal(results(f).length, 1);
  assert.equal(continuations(f).length, 1);
});

test('Chatty stop invalidates an armed proposal and ignores late yes after resume', async () => {
  const f = fixture({ source: 'meeting-tab' });
  speak(f, 'Chatty create a test issue.');
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  participantReply(f, 'Chatty stop');
  await flush();
  assert.equal(f.controller.speech, 'stopped');
  assert.equal(f.muted.at(-1), true);
  assert.equal(f.controller.calls.get('write').status, 'rejected');
  f.controller.resume();
  participantReply(f, 'yes'); await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(continuations(f).length, 0);
  assert.equal(f.approvalRequests.filter(request => request.action === 'cancel').length, 1);
});

test('proposal expiry invalidates old evidence and returns an outcome to Live', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  f.clock.tick(60000); await flush();
  participantReply(f); await flush();
  assert.equal(f.requests.length, 0);
  assert.match(f.controller.calls.get('write').message, /expired/);
  assert.equal(continuations(f).length, 1);
  assert.equal(f.approvalRequests.filter(request => request.action === 'cancel').length, 1);
});

test('immediate post-prompt speech survives delayed server arming but cannot execute before it', async () => {
  const f = fixture();
  const original = f.controller.approvalRequest;
  let resolveArm;
  f.controller.approvalRequest = (action, body) => action === 'arm' ? new Promise(resolve => { resolveArm = resolve; }) : original(action, body);
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await flush();
  const confirmation = f.controller.confirmation;
  f.controller.event({ type: 'session.instructions.appended', client_event_id: confirmation.instructionId });
  f.controller.outputActivity(true); transcript(f, 'output', confirmation.prompt, 1000); f.controller.outputActivity(false);
  participantReply(f, 'yes');
  assert.equal(confirmation.stage, 'arming');
  assert.equal(f.requests.length, 0);
  resolveArm({ armed: true }); await flush();
  f.clock.tick(0); await flush();
  assert.equal(f.requests.length, 1);
});

test('speech overlapping the proposal cannot become a later approval', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await flush();
  const confirmation = f.controller.confirmation;
  f.controller.event({ type: 'session.instructions.appended', client_event_id: confirmation.instructionId });
  f.controller.outputActivity(true); transcript(f, 'output', confirmation.prompt, 1000);
  f.controller.inputActivity(true, { available: true, quietSince: null, quietMs: 0 });
  transcript(f, 'input', 'yes', 900);
  f.controller.outputActivity(false); f.clock.tick(500); await flush();
  f.controller.inputActivity(false, { available: true, quietSince: 1, quietMs: 2000 });
  f.clock.tick(1000); await flush();
  assert.equal(f.requests.length, 0);
  assert.equal(f.approvalRequests.filter(request => request.action === 'voice').length, 0);
});

test('unavailable audio and a fresh unqualified onset invalidate quiet approval evidence', async () => {
  const f = fixture();
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  participantReply(f, 'yes', 800);
  f.controller.inputActivity(false, { available: true, quietSince: null, quietMs: 0 });
  f.clock.tick(2000); await flush();
  assert.equal(f.requests.length, 0);
  f.controller.inputActivity(false, { available: false, quietSince: null, quietMs: 0 });
  f.controller.inputActivity(false, { available: true, quietSince: 1, quietMs: 2000 });
  f.clock.tick(0); await flush();
  assert.equal(f.requests.length, 0);
});

test('meeting confirmation accepts a bare yes then waits for one final audible result', async () => {
  const f = fixture({ source: 'meeting-tab' });
  speak(f, 'Chatty create an issue.');
  f.created(); f.call('write', 'create_issue', { title: 'Test', body: 'Body' }); f.completed();
  await voiceApprove(f, 'yes');
  assert.equal(f.requests.length, 1);
  f.clock.tick(2000);
  assert.equal(f.controller.speech, 'listening');
  f.created('final_response'); f.completed('final_response');
  f.controller.outputActivity(true); f.controller.outputActivity(false);
  f.clock.tick(1500);
  assert.equal(f.controller.speech, 'waiting');
});


test('audio monotonic timestamps and Live media timestamps are not compared with the wall clock', async () => {
  const clock = clockFixture();
  const f = fixture({ timers: clock.timers, now: () => 1900000000000 + clock.now(), tick: clock.tick });
  f.created(); f.call('write', 'create_issue', { title: 'Clock domains', body: 'Body' }); f.completed();
  await spokenPrompt(f);
  f.controller.inputActivity(true, { available: true, observedAt: 17, lastActiveAt: 17, quietSince: null, quietMs: 0 });
  transcript(f, 'input', 'yes', 100000);
  f.controller.inputActivity(false, { available: true, observedAt: 300, lastActiveAt: 40, quietSince: 50, quietMs: 250 });
  clock.tick(1000);
  f.controller.inputActivity(false, { available: true, observedAt: 1300, lastActiveAt: 40, quietSince: 50, quietMs: 1250 });
  clock.tick(0); await flush();
  assert.equal(f.requests.length, 1);
  assert.equal(f.approvalRequests.find(request => request.action === 'voice').quiet_ms, 1250);
});
