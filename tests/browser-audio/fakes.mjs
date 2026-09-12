import { setImmediate } from "node:timers/promises";

export const flush = () => setImmediate();

export class Track extends EventTarget {
  constructor(kind = "audio", settings = {}) {
    super();
    this.kind = kind;
    this.readyState = "live";
    this.enabled = true;
    this.muted = false;
    this.level = 0;
    this.stops = 0;
    this.settings = settings;
  }
  getSettings() { return this.settings; }
  stop() { this.stops++; this.readyState = "ended"; }
  end() { this.readyState = "ended"; this.dispatchEvent(new Event("ended")); }
  mute() { this.muted = true; this.dispatchEvent(new Event("mute")); }
  unmute() { this.muted = false; this.dispatchEvent(new Event("unmute")); }
}

export class Stream extends EventTarget {
  constructor(tracks = []) { super(); this.tracks = [...tracks]; }
  getTracks() { return [...this.tracks]; }
  getAudioTracks() { return this.tracks.filter((track) => track.kind === "audio"); }
  getVideoTracks() { return this.tracks.filter((track) => track.kind === "video"); }
  removeTrack(track) { this.tracks = this.tracks.filter((item) => item !== track); }
}

export function replaceGlobals(values) {
  const previous = Object.fromEntries(Object.keys(values).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries(values)) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  return () => {
    for (const [key, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  };
}

// Deterministic local audio only: no microphone, audio hardware, or API calls.
export function audioAnalysis({ initialState = "running", resumeFails = false, analyserFails = false } = {}) {
  let now = 0;
  let timerId = 0;
  const timers = new Map();
  const contexts = [];
  class Context extends EventTarget {
    state = initialState;
    sources = [];
    analysers = [];
    closes = 0;
    constructor() { super(); contexts.push(this); }
    createAnalyser() {
      if (analyserFails) throw new Error("Analyser unavailable.");
      const analyser = {
        disconnected: false, reads: 0,
        getFloatTimeDomainData(samples) {
          this.reads++;
          samples.fill(this.stream.getAudioTracks()[0].level);
        },
        disconnect() { this.disconnected = true; },
      };
      this.analysers.push(analyser);
      return analyser;
    }
    createMediaStreamSource(stream) {
      const source = {
        stream, disconnected: false,
        connect(node) { node.stream = stream; },
        disconnect() { this.disconnected = true; },
      };
      this.sources.push(source);
      return source;
    }
    change(state) { this.state = state; this.dispatchEvent(new Event("statechange")); }
    async resume() {
      if (resumeFails) throw new Error("Resume denied.");
      this.change("running");
    }
    async close() { this.closes++; this.change("closed"); }
  }
  const restore = replaceGlobals({
    AudioContext: Context,
    performance: { now: () => now },
    setInterval(fn, interval) { const id = ++timerId; timers.set(id, { fn, interval, at: now + interval }); return id; },
    clearInterval(id) { timers.delete(id); },
  });
  return {
    contexts, timers, restore,
    tick(ms) {
      const end = now + ms;
      while (true) {
        const next = [...timers.values()].filter((timer) => timer.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!next) break;
        now = next.at;
        next.at += next.interval;
        next.fn();
      }
      now = end;
    },
  };
}

export function browser() {
  const window = new EventTarget();
  const calls = [];
  const peers = [];
  const audios = [];
  const requests = [];
  class Channel extends EventTarget {
    readyState = "connecting";
    sent = [];
    send(data) {
      if (this.readyState !== "open") throw new Error("Closed channel.");
      this.sent.push(JSON.parse(data));
    }
    close() {
      this.readyState = "closed";
      this.dispatchEvent(new Event("close"));
    }
    receive(event) {
      this.readyState = "open";
      this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(event) }));
    }
  }
  class Peer extends EventTarget {
    iceGatheringState = "new";
    connectionState = "new";
    closed = false;
    tracks = [];
    constructor() { super(); peers.push(this); }
    addTrack(track) { calls.push("addTrack"); this.tracks.push(track); }
    createDataChannel(name) { calls.push(name); this.channel = new Channel(); return this.channel; }
    async createOffer() { calls.push("createOffer"); return { type: "offer", sdp: "initial" }; }
    async setLocalDescription(offer) { calls.push("setLocalDescription"); this.localDescription = offer; }
    async setRemoteDescription(answer) { calls.push("setRemoteDescription"); this.answer = answer; }
    gather() {
      this.localDescription = { type: "offer", sdp: "complete-with-ice" };
      this.iceGatheringState = "complete";
      this.dispatchEvent(new Event("icegatheringstatechange"));
    }
    change(state) { this.connectionState = state; this.dispatchEvent(new Event("connectionstatechange")); }
    receiveTrack(track) {
      const event = new Event("track");
      event.track = track;
      this.dispatchEvent(event);
    }
    close() { this.closed = true; this.change("closed"); }
  }
  class Output extends EventTarget {
    muted = false;
    plays = 0;
    pauses = 0;
    rejectPlayback = false;
    sinkId = "";
    sinks = [];
    src = "";
    loads = 0;
    constructor() { super(); audios.push(this); }
    async play() { this.plays++; if (this.rejectPlayback) throw new Error("Autoplay denied."); }
    pause() { this.pauses++; }
    load() { this.loads++; }
    removeAttribute(name) { if (name === "src") this.src = ""; }
    async setSinkId(deviceId) { this.sinks.push(deviceId); this.sinkId = deviceId; }
  }
  const environment = {
    window, calls, peers, audios, requests,
    response: { session: { id: "live_test" }, transport: { type: "webrtc", sdp: "answer" } },
    status: 201,
  };
  environment.restore = replaceGlobals({
    addEventListener: window.addEventListener.bind(window),
    removeEventListener: window.removeEventListener.bind(window),
    RTCPeerConnection: Peer,
    Audio: Output,
    MediaStream: Stream,
    fetch: async (url, options) => {
      requests.push({ url, ...options });
      return { ok: environment.status < 400, status: environment.status, json: async () => environment.response };
    },
  });
  return environment;
}
