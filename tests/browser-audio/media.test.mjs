import assert from "node:assert/strict";
import test from "node:test";
import { captureInput } from "../../web/media.js";
import { browser, replaceGlobals, Stream, Track } from "./fakes.mjs";

function captureFixture(t, tracks) {
  const env = browser();
  const stream = new Stream(tracks);
  let options;
  const requests = [];
  const restore = replaceGlobals({ navigator: { mediaDevices: {
    getDisplayMedia: async (value) => { options = value; requests.push("display"); return stream; },
    getUserMedia: async (value) => { options = value; requests.push("mic"); return stream; },
  } } });
  t.after(() => { restore(); env.restore(); });
  return { env, stream, requests, get options() { return options; } };
}

test("meeting capture requests tab audio, releases video, and never requests microphone", async (t) => {
  const voice = new Track();
  const video = new Track("video", { displaySurface: "browser" });
  const fixture = captureFixture(t, [voice, video]);
  assert.deepEqual(fixture.requests, []);
  const capture = await captureInput("meeting-tab");
  assert.deepEqual(fixture.requests, ["display"]);
  assert.equal(fixture.options.video.displaySurface, "browser");
  assert.equal(fixture.options.selfBrowserSurface, "exclude");
  assert.equal(fixture.options.systemAudio, "exclude");
  assert.deepEqual(capture.stream.getTracks(), [voice]);
  assert.equal(video.readyState, "ended");
  capture.stop();
  capture.stop();
  assert.equal(voice.stops, 1);
});

test("missing audio rejects and releases the selected display", async (t) => {
  const video = new Track("video");
  captureFixture(t, [video]);
  await assert.rejects(captureInput("meeting-tab"), /Share tab audio/);
  assert.equal(video.readyState, "ended");
});

test("window or screen selection is rejected to avoid broad audio capture", async (t) => {
  const tracks = [new Track(), new Track("video", { displaySurface: "monitor" })];
  captureFixture(t, tracks);
  await assert.rejects(captureInput("meeting-tab"), /browser tab/);
  assert.ok(tracks.every((track) => track.readyState === "ended"));
});

test("revoking an audio track releases all remaining capture tracks", async (t) => {
  const first = new Track();
  const second = new Track();
  captureFixture(t, [first, second]);
  await captureInput("meeting-tab");
  first.end();
  assert.equal(second.readyState, "ended");
});

test("page exit stops microphone capture", async (t) => {
  const voice = new Track();
  const fixture = captureFixture(t, [voice]);
  await captureInput("microphone");
  assert.deepEqual(fixture.requests, ["mic"]);
  assert.equal(fixture.options.video, false);
  fixture.env.window.dispatchEvent(new Event("pagehide"));
  assert.equal(voice.readyState, "ended");
});

test("invalid source and denied permission do not fall back to another capture source", async (t) => {
  const denial = new DOMException("Denied", "NotAllowedError");
  const restore = replaceGlobals({ navigator: { mediaDevices: {
    getDisplayMedia: async () => { throw denial; },
    getUserMedia: () => assert.fail("Must not silently switch to microphone"),
  } } });
  t.after(restore);
  await assert.rejects(captureInput("screen"), /Audio source/);
  await assert.rejects(captureInput("meeting-tab"), (error) => error === denial);
});
