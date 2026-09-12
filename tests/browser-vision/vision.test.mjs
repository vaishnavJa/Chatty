import assert from 'node:assert/strict';
import test from 'node:test';
import { createMeetingVision, frameSize, MAX_FRAME_BYTES } from '../../web/vision.js';
import { browser, flush, replaceGlobals, Stream, Track } from '../browser-audio/fakes.mjs';

const JPEG = `data:image/jpeg;base64,${Buffer.from([255, 216, 255, 224, 255, 217]).toString('base64')}`;
function fixture(t, options = {}) {
  const env = browser();
  const video = Object.assign(new EventTarget(), {
    readyState: 2, videoWidth: 1920, videoHeight: 1080, plays: 0, pauses: 0,
    play: async function () { this.plays++; }, pause() { this.pauses++; },
  });
  const draws = [];
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: (...args) => draws.push(args) }), toDataURL: () => JPEG };
  const track = new Track('video');
  const stream = new Stream([track]);
  const restore = replaceGlobals({ document: { createElement: name => name === 'video' ? video : canvas } });
  const vision = createMeetingVision({ stream, sessionId: options.sessionId ?? 'live_test', onState: options.onState });
  t.after(() => { vision.stop(); restore(); env.restore(); });
  return { env, video, canvas, track, stream, vision, draws };
}

test('constructor and opt-in never upload or open another display picker', async t => {
  const f = fixture(t);
  assert.equal(f.vision.enabled, false);
  await assert.rejects(f.vision.captureFrame(), /vision is off/);
  f.vision.setEnabled(true);
  await flush();
  assert.deepEqual(f.env.requests, []);
  assert.equal(f.video.muted, true);
  assert.equal(f.env.peers.length, 0);
});

test('capture reads actual video pixels at a bounded size then clears the canvas', async t => {
  const f = fixture(t);
  f.vision.setEnabled(true);
  const frame = await f.vision.captureFrame();
  assert.equal(frame.image_data_url, JPEG);
  assert.equal(frame.width, 1280);
  assert.equal(frame.height, 720);
  assert.ok(Math.abs(frame.captured_at - Date.now()) < 1000);
  assert.equal(f.draws[0][0], f.video);
  assert.deepEqual(f.draws[0].slice(1), [0, 0, 1280, 720]);
  assert.equal(f.canvas.width, 0);
  assert.equal(f.canvas.height, 0);
  assert.deepEqual(f.env.requests, []);
});

test('screen question submits one frame with its owning session and tool call', async t => {
  const f = fixture(t, { sessionId: 'session-two' });
  f.vision.setEnabled(true);
  f.env.response = { call_id: 'screen-one', output: '{"ok":true,"answer":"Blue rectangle"}' };
  const result = await f.vision.analyze('What color is the rectangle?', { callId: 'screen-one' });
  assert.equal(result.call_id, 'screen-one');
  const request = f.env.requests[0];
  assert.equal(request.url, '/api/vision/analyze');
  assert.deepEqual(Object.keys(JSON.parse(request.body)).sort(), ['call_id', 'frame', 'question', 'session_id']);
  const body = JSON.parse(request.body);
  assert.equal(body.session_id, 'session-two');
  assert.equal(body.frame.image_data_url, JPEG);
  assert.equal(body.question, 'What color is the rectangle?');
  await assert.rejects(f.vision.analyze('Again', { callId: 'screen-two' }), /Wait a moment/);
  assert.equal(f.env.requests.length, 1);
});

test('oversized screenshots are reduced and never sent beyond the byte limit', async t => {
  const f = fixture(t);
  f.vision.setEnabled(true);
  const attempts = [];
  f.canvas.toDataURL = (type, quality) => {
    attempts.push([f.canvas.width, quality]);
    return attempts.length < 3 ? `data:image/jpeg;base64,${'A'.repeat(Math.ceil(MAX_FRAME_BYTES * 4 / 3) + 8)}` : JPEG;
  };
  const result = await f.vision.captureFrame();
  assert.equal(result.width, 960);
  assert.equal(attempts.length, 3);
  assert.deepEqual(f.env.requests, []);
});

test('stop aborts a pending request and discards its late answer', async t => {
  const f = fixture(t);
  let resolveFetch;
  const restore = replaceGlobals({ fetch: async () => new Promise(resolve => { resolveFetch = resolve; }) });
  t.after(restore);
  f.vision.setEnabled(true);
  const pending = f.vision.analyze('Read this slide', { callId: 'one' });
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  await flush();
  f.vision.stop();
  resolveFetch({ ok: true, json: async () => ({ call_id: 'one', output: 'old screen' }) });
  await rejected;
  assert.equal(f.video.srcObject, null);
  assert.equal(f.track.readyState, 'ended');
  assert.equal(f.canvas.width, 0);
});

test('clear invalidates an in-flight result even if vision stays enabled', async t => {
  const f = fixture(t);
  let resolveJson;
  const restore = replaceGlobals({ fetch: async () => ({ ok: true, json: async () => new Promise(resolve => { resolveJson = resolve; }) }) });
  t.after(restore);
  f.vision.setEnabled(true);
  const pending = f.vision.analyze('What is visible?', { callId: 'one' });
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  await flush();
  f.vision.clear();
  resolveJson({ call_id: 'one', output: 'obsolete pixels' });
  await rejected;
  assert.equal(f.vision.enabled, true);
});

test('disabled, muted, and ended sources cannot produce a frame', async t => {
  const f = fixture(t);
  f.vision.setEnabled(true);
  f.track.muted = true;
  await assert.rejects(f.vision.captureFrame(), /source is unavailable/);
  f.track.muted = false;
  f.vision.setEnabled(false);
  await assert.rejects(f.vision.captureFrame(), /vision is off/);
  f.vision.setEnabled(true);
  f.track.end();
  await assert.rejects(f.vision.captureFrame(), /vision is off/);
  assert.deepEqual(f.env.requests, []);
});

test('caller cancellation and cross-call receipts are rejected', async t => {
  const f = fixture(t);
  f.vision.setEnabled(true);
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(f.vision.analyze('Read this', { callId: 'one', signal: abort.signal }), { name: 'AbortError' });
  assert.equal(f.env.requests.length, 0);
  f.env.response = { call_id: 'someone-elses-call', output: 'answer' };
  await assert.rejects(f.vision.analyze('Read this', { callId: 'one' }), /invalid tool receipt/);
});

test('frame sizes preserve aspect ratio and invalid dimensions fail', () => {
  assert.deepEqual(frameSize(500, 1000), { width: 500, height: 1000 });
  assert.deepEqual(frameSize(1080, 1920), { width: 720, height: 1280 });
  assert.throws(() => frameSize(0, 100), /no readable video frame/);
  assert.throws(() => frameSize(NaN, 100), /no readable video frame/);
});
