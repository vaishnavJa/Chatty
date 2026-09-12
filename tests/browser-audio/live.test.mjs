import assert from "node:assert/strict";
import test from "node:test";
import { connectLive } from "../../web/live.js";
import { browser, flush, replaceGlobals, Stream, Track } from "./fakes.mjs";

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
