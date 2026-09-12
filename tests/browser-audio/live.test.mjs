import assert from "node:assert/strict";
import test from "node:test";
import { connectLive } from "../../web/live.js";
import { audioAnalysis, browser, flush, replaceGlobals, Stream, Track } from "./fakes.mjs";

function setup(t, options = {}) {
  const env = browser();
  const input = new Track();
  const stream = new Stream([input]);
  const states = [];
  const events = [];
  const connecting = connectLive({
    stream,
    onState: (state, details) => states.push({ state, ...details }),
    onEvent: (event) => events.push(event),
    ...options,
  });
  connecting.catch(() => {});
  t.after(() => {
    env.window.dispatchEvent(new Event("pagehide"));
    env.restore();
  });
  return { env, input, stream, states, events, connecting, get peer() { return env.peers[0]; } };
}

async function negotiate(fixture) {
  await flush();
  fixture.peer.gather();
  await flush();
}

async function ready(fixture) {
  await negotiate(fixture);
  fixture.peer.channel.receive({ type: "session.started", session: { id: "live_test" } });
  return fixture.connecting;
}

function finalized(fixture) {
  fixture.peer.channel.receive({ type: "session.closed", reason: "close_requested", usage: { seconds: 8 } });
}

test("creates channel before SDP, posts gathered SDP, and waits for session.started", async (t) => {
  const f = setup(t);
  await flush();
  assert.deepEqual(f.env.calls, ["addTrack", "oai-events", "createOffer", "setLocalDescription"]);
  assert.equal(f.env.requests.length, 0);
  await negotiate(f);
  assert.equal(f.env.requests[0].url, "/api/live/session");
  assert.deepEqual(JSON.parse(f.env.requests[0].body), { sdp: "complete-with-ice" });
  assert.deepEqual(f.env.requests[0].headers, { "Content-Type": "application/json" });
  assert.deepEqual(f.peer.answer, { type: "answer", sdp: "answer" });
  let resolved = false;
  f.connecting.then(() => { resolved = true; });
  await flush();
  assert.equal(resolved, false);
  f.peer.channel.receive({ type: "session.started", session: { id: "live_test" } });
  const live = await f.connecting;
  assert.equal(live.sessionId, "live_test");
  live.send({ type: "response.create" });
  assert.deepEqual(f.peer.channel.sent, [{ type: "response.create" }]);
  finalized(f);
});

test("Stop immediately mutes output and stays muted across late audio tracks", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const first = new Track();
  f.peer.receiveTrack(first);
  assert.equal(f.env.audios[0].muted, true);
  assert.equal(f.env.audios[0].plays, 0);
  await live.setOutputMuted(false);
  live.setOutputMuted(true);
  assert.equal(f.env.audios[0].muted, true);
  f.peer.receiveTrack(new Track());
  assert.equal(f.env.audios[0].muted, true);
  live.setInputEnabled(false);
  assert.equal(f.input.enabled, false);
  live.setInputEnabled(true);
  assert.equal(f.input.enabled, true);
  await live.setOutputMuted(false);
  assert.equal(f.env.audios[0].muted, false);
  finalized(f);
  assert.equal(first.readyState, "ended");
});

test("close waits for final usage, rejects new work, and releases resources once", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const closing = live.close();
  assert.equal(live.close(), closing);
  assert.equal(f.env.audios[0].muted, true);
  assert.equal(f.input.enabled, false);
  assert.equal(f.peer.closed, false);
  assert.deepEqual(f.peer.channel.sent, [{ type: "session.close" }]);
  assert.throws(() => live.send({ type: "response.create" }), /not ready/);
  live.setInputEnabled(true);
  live.setOutputMuted(false);
  assert.equal(f.input.enabled, false);
  assert.equal(f.env.audios[0].muted, true);
  finalized(f);
  assert.deepEqual(await closing, { finalized: true, reason: "close_requested", usage: { seconds: 8 } });
  assert.equal(f.peer.closed, true);
  assert.equal(f.input.stops, 1);
  assert.equal(f.env.audios[0].srcObject, null);
  assert.equal(f.events.at(-1).type, "session.closed");
});

test("close timeout releases audio and reports unconfirmed finalization", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(t);
  const live = await ready(f);
  const closing = live.close();
  t.mock.timers.tick(5_000);
  assert.equal((await closing).finalized, false);
  assert.equal(f.states.at(-1).reason, "finalization_timeout");
  assert.equal(f.input.readyState, "ended");
  assert.equal(f.peer.closed, true);
});

test("ICE timeout rejects startup and releases input", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(t);
  await flush();
  t.mock.timers.tick(10_000);
  await assert.rejects(f.connecting, /ICE candidates/);
  assert.equal(f.input.readyState, "ended");
  assert.equal(f.env.requests.length, 0);
});

test("session.started timeout does not leave a peer or track alive", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(t);
  await negotiate(f);
  t.mock.timers.tick(30_000);
  await assert.rejects(f.connecting, /session.started/);
  assert.equal(f.peer.closed, true);
  assert.equal(f.input.readyState, "ended");
});

test("abort during ICE cancels startup without a backend request", async (t) => {
  const controller = new AbortController();
  const f = setup(t, { signal: controller.signal });
  await flush();
  controller.abort();
  await assert.rejects(f.connecting, /canceled|closed/);
  assert.equal(f.env.requests.length, 0);
  assert.equal(f.input.readyState, "ended");
});

test("abort during HTTP startup aborts the request and releases capture", async (t) => {
  const controller = new AbortController();
  const f = setup(t, { signal: controller.signal });
  let requestSignal;
  const restore = replaceGlobals({ fetch: (url, { signal }) => new Promise((resolve, reject) => {
    requestSignal = signal;
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  }) });
  t.after(restore);
  await negotiate(f);
  controller.abort();
  await assert.rejects(f.connecting, /closed/);
  assert.equal(requestSignal.aborted, true);
  assert.equal(f.peer.closed, true);
  assert.equal(f.input.readyState, "ended");
});

test("permission revocation closes an active session and mutes instantly", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  f.input.end();
  assert.equal(f.env.audios[0].muted, true);
  assert.deepEqual(f.peer.channel.sent, [{ type: "session.close" }]);
  finalized(f);
  assert.equal((await live.close()).finalized, true);
});

test("temporary disconnect can recover; permanent loss is not finalization", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(t);
  const live = await ready(f);
  f.peer.change("disconnected");
  assert.equal(f.states.at(-1).state, "reconnecting");
  f.peer.change("connected");
  assert.equal(f.states.at(-1).state, "ready");
  t.mock.timers.tick(5_000);
  assert.equal(f.peer.closed, false);
  f.peer.change("disconnected");
  t.mock.timers.tick(5_000);
  assert.equal((await live.close()).finalized, false);
  assert.equal(f.peer.closed, true);
});

test("a channel close before final event reports incomplete finalization", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  f.peer.channel.close();
  assert.equal((await live.close()).finalized, false);
  assert.equal(f.input.readyState, "ended");
});

test("autoplay failure is visible and Resume retries playback", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  f.env.audios[0].rejectPlayback = true;
  await live.setOutputMuted(false);
  f.peer.receiveTrack(new Track());
  await flush();
  assert.equal(f.states.at(-1).state, "playback-blocked");
  f.env.audios[0].rejectPlayback = false;
  await live.setOutputMuted(false);
  assert.equal(f.env.audios[0].plays, 2);
  finalized(f);
});

test("malformed backend answer releases the stream", async (t) => {
  const f = setup(t);
  f.env.response = { session: { id: "live_test" } };
  await negotiate(f);
  await assert.rejects(f.connecting, /invalid Live/);
  assert.equal(f.input.readyState, "ended");
});

test("HTTP errors do not render an untrusted server response body", async (t) => {
  const f = setup(t);
  f.env.status = 500;
  await negotiate(f);
  await assert.rejects(f.connecting, /HTTP 500/);
  assert.equal(f.peer.closed, true);
});

test("startup rejects a mismatched session ID", async (t) => {
  const f = setup(t);
  await negotiate(f);
  f.peer.channel.receive({ type: "session.started", session: { id: "different" } });
  await assert.rejects(f.connecting, /session ID/);
  assert.equal(f.peer.closed, true);
});

test("function events are forwarded once and do not trigger another HTTP request", async (t) => {
  const f = setup(t);
  await ready(f);
  const event = { type: "response.event", event: {
    type: "response.output_item.done", item: { type: "function_call", name: "create_issue" },
  } };
  f.peer.channel.receive(event);
  assert.deepEqual(f.events.at(-1), event);
  assert.equal(f.env.requests.length, 1);
  finalized(f);
});

test("already aborted startup releases input without constructing a peer", async (t) => {
  const controller = new AbortController();
  controller.abort();
  const f = setup(t, { signal: controller.signal });
  await assert.rejects(f.connecting, { name: "AbortError" });
  assert.equal(f.env.peers.length, 0);
  assert.equal(f.input.readyState, "ended");
});

test("page exit silences playback and releases input without waiting for finalization", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  await live.setOutputMuted(false);
  f.env.window.dispatchEvent(new Event("pagehide"));
  assert.equal(f.input.readyState, "ended");
  assert.equal(f.env.audios[0].muted, true);
  assert.equal(f.peer.closed, true);
  assert.equal((await live.close()).finalized, false);
});

test("late malformed data cannot leave an active microphone", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  f.peer.channel.dispatchEvent(new MessageEvent("message", { data: "{" }));
  assert.equal(f.input.readyState, "ended");
  assert.equal((await live.close()).finalized, false);
});

test("pre-start model audio remains muted until explicit UI permission", async (t) => {
  const f = setup(t);
  await negotiate(f);
  f.peer.receiveTrack(new Track());
  assert.equal(f.env.audios[0].muted, true);
  assert.equal(f.env.audios[0].plays, 0);
  f.peer.channel.receive({ type: "session.started", session: { id: "live_test" } });
  const live = await f.connecting;
  assert.equal(f.env.audios[0].muted, true);
  await live.setOutputMuted(false);
  assert.equal(f.env.audios[0].plays, 1);
  finalized(f);
});

test("selected output is applied before negotiation without enabling speech", async (t) => {
  const f = setup(t, { outputDeviceId: "virtual-cable" });
  const live = await ready(f);
  assert.equal(live.outputDeviceId, "virtual-cable");
  assert.deepEqual(f.env.audios[0].sinks, ["virtual-cable"]);
  assert.equal(f.env.audios[0].muted, true);
  assert.equal(f.env.audios[0].plays, 0);
  assert.ok(f.states.some((event) => event.state === "output-device-selected" && event.deviceId === "virtual-cable"));
  finalized(f);
});

test("failed startup output selection releases input without opening an API session", async (t) => {
  const f = setup(t, { outputDeviceId: "removed-cable" });
  f.env.audios[0].setSinkId = async () => { throw new DOMException("Cable unavailable.", "NotFoundError"); };
  await assert.rejects(f.connecting, /Cable unavailable/);
  assert.equal(f.env.requests.length, 0);
  assert.equal(f.input.readyState, "ended");
  assert.equal(f.peer.closed, true);
  assert.equal(f.env.audios[0].muted, true);
});

test("Stop during a pending device switch cannot be undone by its completion", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const audio = f.env.audios[0];
  f.peer.receiveTrack(new Track());
  await live.setOutputMuted(false);
  let finish;
  audio.setSinkId = (deviceId) => new Promise((resolve) => { finish = () => { audio.sinkId = deviceId; resolve(); }; });
  const changing = live.setOutputDevice("virtual-cable");
  assert.equal(audio.muted, true);
  await flush();
  live.setOutputMuted(true);
  finish();
  await changing;
  assert.equal(audio.muted, true);
  await live.setOutputMuted(false);
  assert.equal(audio.muted, false);
  finalized(f);
});

test("device selection failures stay silent until routing is explicitly repaired", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const audio = f.env.audios[0];
  audio.setSinkId = async () => { throw new DOMException("Device removed.", "NotFoundError"); };
  await assert.rejects(live.setOutputDevice("missing"), /Device removed/);
  live.setOutputMuted(false);
  f.peer.receiveTrack(new Track());
  assert.equal(audio.muted, true);
  assert.equal(audio.plays, 0);
  assert.equal(f.states.at(-1).state, "output-device-error");
  audio.setSinkId = async (deviceId) => { audio.sinkId = deviceId; };
  await live.setOutputDevice("cable");
  assert.equal(audio.muted, false);
  assert.equal(live.outputDeviceId, "cable");
  finalized(f);
});

test("concurrent output changes are serialized and remain muted until the last selection", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const audio = f.env.audios[0];
  const pending = [];
  audio.setSinkId = (deviceId) => new Promise((resolve) => { pending.push(() => { audio.sinkId = deviceId; resolve(); }); });
  const first = live.setOutputDevice("first");
  const last = live.setOutputDevice("last");
  await live.setOutputMuted(false);
  await flush();
  assert.equal(pending.length, 1);
  pending[0]();
  await first;
  assert.equal(audio.muted, true);
  await flush();
  assert.equal(pending.length, 2);
  pending[1]();
  await last;
  assert.equal(audio.muted, false);
  assert.equal(live.outputDeviceId, "last");
  finalized(f);
});

test("close during output selection cannot resume playback or accept another selection", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  const audio = f.env.audios[0];
  let finish;
  audio.setSinkId = () => new Promise((resolve) => { finish = resolve; });
  const changing = live.setOutputDevice("cable");
  await flush();
  live.setOutputMuted(false);
  const closed = live.close();
  finish();
  await assert.rejects(changing, /closed/);
  await assert.rejects(live.setOutputDevice("cable"), /closed/);
  assert.equal(audio.muted, true);
  finalized(f);
  await closed;
  assert.equal(audio.srcObject, null);
});

test("unsupported output selection cannot silently fall back to laptop speakers", async (t) => {
  const f = setup(t);
  const live = await ready(f);
  f.env.audios[0].setSinkId = undefined;
  await assert.rejects(live.setOutputDevice("cable"), /cannot select/);
  live.setOutputMuted(false);
  assert.equal(f.env.audios[0].muted, true);
  await live.setOutputDevice("");
  assert.equal(f.env.audios[0].muted, false);
  finalized(f);
});

test("output activity observes only remote audio and stops with mute/cleanup", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  let level = 0.05;
  let observer;
  let source;
  const context = {
    state: "running",
    createAnalyser() { observer = { getFloatTimeDomainData: (samples) => samples.fill(level) }; return observer; },
    createMediaStreamSource(stream) {
      assert.deepEqual(stream.getTracks(), [remote]);
      source = { connect: (node) => assert.equal(node, observer), disconnect: () => {} };
      return source;
    },
    async close() { this.state = "closed"; },
  };
  const restore = replaceGlobals({ AudioContext: class { constructor() { return context; } } });
  t.after(restore);
  const changes = [];
  const f = setup(t, { onOutputActivity: (active) => changes.push(active) });
  const live = await ready(f);
  const remote = new Track();
  f.peer.receiveTrack(remote);
  t.mock.timers.tick(100);
  assert.deepEqual(changes, []);
  await live.setOutputMuted(false);
  t.mock.timers.tick(100);
  assert.deepEqual(changes, [true]);
  level = 0;
  t.mock.timers.tick(100);
  assert.deepEqual(changes, [true, false]);
  level = 0.05;
  t.mock.timers.tick(100);
  live.setOutputMuted(true);
  assert.deepEqual(changes, [true, false, true, false]);
  finalized(f);
  assert.equal(context.state, "closed");
  t.mock.timers.tick(1000);
  assert.equal(changes.length, 4);
});

test("unavailable activity detection leaves voice transport working with visible fallback", async (t) => {
  const restore = replaceGlobals({ AudioContext: undefined });
  t.after(restore);
  const f = setup(t, { onOutputActivity: () => {} });
  const live = await ready(f);
  f.peer.receiveTrack(new Track());
  assert.equal(f.states.at(-1).state, "output-activity-unavailable");
  await live.setOutputMuted(false);
  assert.equal(f.env.audios[0].muted, false);
  assert.equal(f.env.audios[0].plays, 1);
  finalized(f);
});

function inputActivitySetup(t, options = {}) {
  const analysis = audioAnalysis(options);
  const activity = [];
  const f = setup(t, { onInputActivity: (active, details) => activity.push({ active, ...details }), ...options.live });
  t.after(analysis.restore);
  return { ...f, peer: f.peer, analysis, activity };
}

test("initial and long input silence never provide approval evidence", async (t) => {
  const f = inputActivitySetup(t);
  await ready(f);
  f.analysis.tick(5000);
  assert.ok(f.activity.length > 1);
  for (const event of f.activity) {
    assert.equal(event.active, false);
    assert.equal(event.available, true);
    assert.equal(event.lastActiveAt, null);
    assert.equal(event.quietSince, null);
    assert.equal(event.quietMs, 0);
  }
  assert.equal(f.activity.at(-1).observedAt, 5000);
  assert.deepEqual(f.analysis.contexts[0].sources[0].stream.getTracks(), [f.input]);
  finalized(f);
});

test("input speech requires sustained activity and reports actual quiet with monotonic timing", async (t) => {
  const f = inputActivitySetup(t);
  await ready(f);
  f.input.level = 0.05;
  f.analysis.tick(150);
  assert.equal(f.activity.at(-1).active, false);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  f.analysis.tick(50);
  assert.deepEqual(f.activity.at(-1), {
    active: true, available: true, observedAt: 200, lastActiveAt: 200,
    quietSince: null, quietMs: 0, reason: "speech",
  });
  f.input.level = 0.01; // Hysteresis keeps quieter syllables inside the utterance.
  f.analysis.tick(50);
  assert.equal(f.activity.at(-1).active, true);
  assert.equal(f.activity.at(-1).lastActiveAt, 250);
  f.input.level = 0;
  f.analysis.tick(250);
  assert.equal(f.activity.at(-1).active, true);
  f.analysis.tick(50);
  assert.deepEqual(f.activity.at(-1), {
    active: false, available: true, observedAt: 550, lastActiveAt: 250,
    quietSince: 300, quietMs: 250, reason: "quiet",
  });
  f.analysis.tick(750);
  assert.equal(f.activity.at(-1).quietMs, 1000);
  assert.equal(f.activity.at(-1).observedAt, 1300);
  f.input.level = 0.03; // Fresh onset immediately removes the eligible quiet window.
  f.analysis.tick(50);
  assert.equal(f.activity.at(-1).quietSince, null);
  assert.equal(f.activity.at(-1).quietMs, 0);
  finalized(f);
});

test("brief input noise never qualifies as approval speech", async (t) => {
  const f = inputActivitySetup(t);
  await ready(f);
  for (let count = 0; count < 3; count++) {
    f.input.level = 0.2;
    f.analysis.tick(100);
    f.input.level = 0;
    f.analysis.tick(1000);
  }
  assert.ok(f.activity.every((event) => !event.active && event.lastActiveAt === null && event.quietMs === 0));
  finalized(f);
});

test("disabled or browser-muted input clears evidence and must hear fresh activity after recovery", async (t) => {
  const f = inputActivitySetup(t);
  const live = await ready(f);
  f.input.level = 0.05;
  f.analysis.tick(200);
  assert.equal(f.activity.at(-1).active, true);
  live.setInputEnabled(false);
  assert.equal(f.activity.at(-1).available, false);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  f.analysis.tick(1500);
  assert.equal(f.activity.at(-1).quietMs, 0);
  live.setInputEnabled(true);
  f.input.level = 0;
  f.analysis.tick(1500);
  assert.equal(f.activity.at(-1).available, true);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  f.input.level = 0.05;
  f.analysis.tick(200);
  f.input.mute();
  assert.equal(f.activity.at(-1).available, false);
  f.analysis.tick(1500);
  assert.equal(f.activity.at(-1).quietMs, 0);
  f.input.unmute();
  f.input.level = 0;
  f.analysis.tick(1500);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  f.input.enabled = false; // Direct track changes are also caught on the next sample.
  f.analysis.tick(50);
  assert.equal(f.activity.at(-1).available, false);
  finalized(f);
});

test("input and output activity use separate streams and Stop keeps listening", async (t) => {
  const output = [];
  const f = inputActivitySetup(t, { live: { onOutputActivity: (active) => output.push(active) } });
  const live = await ready(f);
  const remote = new Track();
  remote.level = 0.05;
  f.peer.receiveTrack(remote);
  await live.setOutputMuted(false);
  f.analysis.tick(500);
  assert.deepEqual(output, [true]);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  assert.deepEqual(f.analysis.contexts[0].sources[0].stream.getTracks(), [f.input]);
  assert.deepEqual(f.analysis.contexts[1].sources[0].stream.getTracks(), [remote]);
  live.setOutputMuted(true);
  f.input.level = 0.05;
  f.analysis.tick(200);
  assert.equal(f.activity.at(-1).active, true);
  assert.equal(f.input.enabled, true);
  assert.deepEqual(output, [true, false]);
  finalized(f);
});

test("revoked source immediately stops the input observer and releases its nodes", async (t) => {
  const f = inputActivitySetup(t);
  await ready(f);
  f.input.level = 0.05;
  f.analysis.tick(200);
  f.input.end();
  assert.equal(f.activity.at(-1).available, false);
  assert.equal(f.activity.at(-1).quietMs, 0);
  assert.equal(f.analysis.timers.size, 0);
  const context = f.analysis.contexts[0];
  assert.equal(context.closes, 1);
  assert.equal(context.sources[0].disconnected, true);
  assert.equal(context.analysers[0].disconnected, true);
  const count = f.activity.length;
  f.input.mute();
  context.change("suspended");
  f.analysis.tick(5000);
  assert.equal(f.activity.length, count);
  finalized(f);
  assert.equal(context.closes, 1);
});

test("abort during startup removes activity timers, context, and track listeners", async (t) => {
  const controller = new AbortController();
  const f = inputActivitySetup(t, { live: { signal: controller.signal } });
  await flush();
  controller.abort();
  await assert.rejects(f.connecting, /canceled|closed/);
  assert.equal(f.analysis.timers.size, 0);
  assert.equal(f.analysis.contexts[0].state, "closed");
  const count = f.activity.length;
  f.input.mute();
  f.analysis.contexts[0].change("suspended");
  f.analysis.tick(5000);
  assert.equal(f.activity.length, count);
});

test("failed or suspended audio context cannot generate a quiet approval window", async (t) => {
  const f = inputActivitySetup(t, { initialState: "suspended", resumeFails: true });
  await ready(f);
  f.input.level = 0.2;
  f.analysis.tick(2000);
  assert.ok(f.activity.every((event) => !event.available && event.lastActiveAt === null && event.quietMs === 0));
  const context = f.analysis.contexts[0];
  context.change("running");
  f.analysis.tick(200);
  assert.equal(f.activity.at(-1).active, true);
  context.change("suspended");
  assert.equal(f.activity.at(-1).available, false);
  f.input.level = 0;
  context.change("running");
  f.analysis.tick(2000);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  assert.equal(f.activity.at(-1).quietMs, 0);
  finalized(f);
});

test("unavailable input analyser fails closed while ordinary voice transport still works", async (t) => {
  const f = inputActivitySetup(t, { analyserFails: true });
  const live = await ready(f);
  assert.equal(f.activity.at(-1).available, false);
  assert.equal(f.activity.at(-1).quietSince, null);
  assert.equal(f.analysis.contexts[0].state, "closed");
  assert.equal(f.analysis.timers.size, 0);
  assert.ok(f.states.some((event) => event.state === "input-activity-unavailable"));
  f.peer.receiveTrack(new Track());
  await live.setOutputMuted(false);
  assert.equal(f.env.audios[0].muted, false);
  finalized(f);
});

test("input activity callback is optional and allocates no observer when omitted", async (t) => {
  const analysis = audioAnalysis();
  const f = setup(t);
  t.after(analysis.restore);
  const live = await ready(f);
  assert.equal(analysis.contexts.length, 0);
  assert.equal(analysis.timers.size, 0);
  live.setInputEnabled(false);
  live.setInputEnabled(true);
  finalized(f);
});

test("invalid analyser samples invalidate prior speech and release the observer", async (t) => {
  const f = inputActivitySetup(t);
  await ready(f);
  f.input.level = 0.05;
  f.analysis.tick(200);
  assert.equal(f.activity.at(-1).active, true);
  f.input.level = NaN;
  f.analysis.tick(50);
  assert.equal(f.activity.at(-1).available, false);
  assert.equal(f.activity.at(-1).lastActiveAt, null);
  assert.equal(f.activity.at(-1).quietMs, 0);
  assert.equal(f.analysis.timers.size, 0);
  assert.equal(f.analysis.contexts[0].state, "closed");
  finalized(f);
});
