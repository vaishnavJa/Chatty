const ICE_TIMEOUT_MS = 10_000;
const START_TIMEOUT_MS = 30_000;
const CLOSE_TIMEOUT_MS = 5_000;
const DISCONNECT_TIMEOUT_MS = 5_000;

function waitForIce(peer, signal) {
  return new Promise((resolve, reject) => {
    const finish = (error) => {
      clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", check);
      signal.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve();
    };
    const check = () => {
      if (peer.iceGatheringState === "complete") finish();
    };
    const abort = () => finish(signal.reason);
    const timer = setTimeout(() => finish(new Error("Timed out gathering ICE candidates.")), ICE_TIMEOUT_MS);
    peer.addEventListener("icegatheringstatechange", check);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    else check();
  });
}

/**
 * Open a browser Live connection through Chatty's same-origin backend.
 * Owns the supplied stream until close/failure. Does not execute tools.
 * onState(state, details): see docs/meeting-setup.md for the callback contract.
 */
export async function connectLive({ stream, onEvent = () => {}, onState = () => {}, onOutputActivity, signal, outputDeviceId = "" }) {
  const inputTracks = stream?.getAudioTracks() ?? [];
  if (!inputTracks.some((track) => track.readyState === "live")) {
    stream?.getTracks().forEach((track) => track.stop());
    throw new Error("Live needs a stream containing live audio.");
  }
  let peer;
  let channel;
  let audio;
  let sessionId;
  let ready = false;
  let closing = false;
  let disposed = false;
  let closeTimer;
  let disconnectTimer;
  let startTimer;
  let outputMuted = true;
  let outputSwitches = 0;
  let outputFailed = false;
  let outputQueue = Promise.resolve();
  let activityContext;
  let activitySource;
  let activityTimer;
  let outputActive = false;
  const pending = new AbortController();
  const remoteTracks = new Set();
  const listeners = [];
  let resolveStarted;
  let rejectStarted;
  const started = new Promise((resolve, reject) => {
    resolveStarted = resolve;
    rejectStarted = reject;
  });
  // A capture or channel failure can happen while createOffer/fetch is pending.
  // Observe rejection now, and rethrow it at the startup await below.
  started.catch(() => {});
  let resolveClosed;
  const closed = new Promise((resolve) => { resolveClosed = resolve; });
  const state = (name, details = {}) => onState(name, { sessionId, ...details });
  function listen(target, name, handler) {
    target.addEventListener(name, handler);
    listeners.push(() => target.removeEventListener(name, handler));
  }
  function setInputEnabled(enabled) {
    for (const track of inputTracks) track.enabled = Boolean(enabled) && !closing && !disposed;
  }
  function playOutput() {
    if (!audio?.srcObject || closing || disposed || audio.muted) return;
    if (activityContext?.state === "suspended") activityContext.resume().catch(() => {});
    return audio.play().catch(() => {
      if (!closing && !disposed && !audio.muted) {
        state("playback-blocked", { message: "Click Resume to allow Chatty audio playback." });
      }
    });
  }
  function setOutputMuted(muted) {
    outputMuted = Boolean(muted);
    return applyOutputMute();
  }
  function applyOutputMute() {
    if (!audio) return;
    audio.muted = outputMuted || outputSwitches > 0 || outputFailed || closing || disposed;
    if (audio.muted) reportOutputActivity(false);
    if (!audio.muted) return playOutput();
  }
  function setOutputDevice(deviceId) {
    if (typeof deviceId !== "string") return Promise.reject(new TypeError("Audio output device ID must be a string."));
    if (!audio || closing || disposed) return Promise.reject(new Error("Live is closed; output cannot be changed."));
    // Silence before the async device change. Stop/Resume updates the desired
    // mute state while routing is pending, rather than being undone on success.
    outputSwitches++;
    applyOutputMute();
    const change = outputQueue.catch(() => {}).then(async () => {
      try {
        if (closing || disposed) throw new Error("Live closed before output could be changed.");
        if (typeof audio.setSinkId !== "function") {
          if (deviceId !== "") throw new Error("This browser cannot select an audio output. Use Chrome on localhost or HTTPS.");
        } else {
          await audio.setSinkId(deviceId);
        }
        if (closing || disposed) throw new Error("Live closed while output was changing.");
        outputFailed = false;
        state("output-device-selected", { deviceId });
        return deviceId;
      } catch (error) {
        outputFailed = true;
        if (!closing && !disposed) state("output-device-error", { message: `Audio output could not be selected: ${error.message}` });
        throw error;
      } finally {
        outputSwitches--;
        applyOutputMute();
      }
    });
    outputQueue = change;
    return change;
  }
  function reportOutputActivity(active) {
    if (outputActive === active) return;
    outputActive = active;
    onOutputActivity?.(active);
  }
  function observeOutputActivity() {
    if (!onOutputActivity || !audio?.srcObject) return;
    clearInterval(activityTimer);
    activitySource?.disconnect();
    try {
      activityContext ??= new AudioContext();
      const analyser = activityContext.createAnalyser();
      analyser.fftSize = 512;
      const samples = new Float32Array(analyser.fftSize);
      activitySource = activityContext.createMediaStreamSource(audio.srcObject);
      // Never connect this observer to a speaker. Playback uses only audio's sink.
      activitySource.connect(analyser);
      activityTimer = setInterval(() => {
        if (disposed || closing || audio.muted || activityContext.state !== "running") {
          reportOutputActivity(false);
          return;
        }
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
        reportOutputActivity(rms > 0.01);
      }, 100);
    } catch {
      state("output-activity-unavailable", { message: "Automatic reply silence detection is unavailable; use Stop speaking." });
    }
  }
  function cleanup(result) {
    if (disposed) return;
    disposed = true;
    ready = false;
    clearTimeout(startTimer);
    clearTimeout(closeTimer);
    clearTimeout(disconnectTimer);
    clearInterval(activityTimer);
    activitySource?.disconnect();
    activityContext?.close().catch(() => {});
    reportOutputActivity(false);
    pending.abort(new DOMException("Live connection closed.", "AbortError"));
    for (const remove of listeners) remove();
    stream.getTracks().forEach((track) => track.stop());
    remoteTracks.forEach((track) => track.stop());
    if (audio) {
      audio.muted = true;
      audio.pause();
      audio.srcObject = null;
    }
    channel?.close();
    peer?.close();
    rejectStarted(new Error(result.message ?? "Live closed before session.started."));
    resolveClosed(result);
    state("closed", result);
  }
  function fail(error) {
    if (disposed) return;
    state("error", { message: error.message });
    rejectStarted(error);
    cleanup({ finalized: false, reason: "connection_failed", message: error.message });
  }
  function close() {
    if (closing || disposed) return closed;
    closing = true;
    setOutputMuted(true);
    setInputEnabled(false);
    clearTimeout(disconnectTimer);
    state("closing");
    if (!ready || channel?.readyState !== "open") {
      cleanup({ finalized: false, reason: "connection_unavailable" });
      return closed;
    }
    // Keep the channel alive for session.closed and its final usage snapshot.
    closeTimer = setTimeout(() => cleanup({
      finalized: false,
      reason: "finalization_timeout",
      message: "Live did not confirm final usage before the close timeout.",
    }), CLOSE_TIMEOUT_MS);
    try {
      channel.send(JSON.stringify({ type: "session.close" }));
    } catch (error) {
      fail(error);
    }
    return closed;
  }
  function send(event) {
    if (!ready || closing || disposed || channel?.readyState !== "open") {
      throw new Error("Live is not ready to receive commands.");
    }
    if (!event || typeof event !== "object" || typeof event.type !== "string") {
      throw new TypeError("Live commands must be event objects with a type.");
    }
    if (event.type === "session.close") return close();
    channel.send(JSON.stringify(event));
  }

  try {
    if (signal?.aborted) throw signal.reason ?? new DOMException("Aborted", "AbortError");
    peer = new RTCPeerConnection();
    audio = new Audio();
    audio.autoplay = true;
    // The UI must explicitly allow speech after applying its wake/Resume policy.
    audio.muted = true;
    state("connecting");
    startTimer = setTimeout(() => fail(new Error("Timed out waiting for Live session.started.")), START_TIMEOUT_MS);
    if (signal) listen(signal, "abort", () => {
      if (ready) close();
      else fail(new DOMException("Live startup was canceled.", "AbortError"));
    });
    listen(globalThis, "pagehide", () => {
      close();
      cleanup({ finalized: false, reason: "page_hidden" });
    });
    for (const track of inputTracks) {
      listen(track, "ended", () => {
        state("error", { message: "Audio capture ended. Start again and select the audio source." });
        close();
      });
      peer.addTrack(track, stream);
    }
    listen(stream, "inactive", close);
    listen(peer, "track", ({ track }) => {
      if (disposed) { track.stop(); return; }
      remoteTracks.add(track);
      if (track.kind !== "audio") { track.stop(); return; }
      audio.srcObject = new MediaStream([...remoteTracks].filter((item) => item.kind === "audio"));
      observeOutputActivity();
      playOutput();
    });
    listen(peer, "connectionstatechange", () => {
      if (disposed) return;
      if (peer.connectionState === "failed" || peer.connectionState === "closed") {
        fail(new Error("Live WebRTC connection failed before finalization."));
      } else if (peer.connectionState === "disconnected" && !closing) {
        state("reconnecting", { message: "Live connection interrupted; waiting briefly for recovery." });
        disconnectTimer ??= setTimeout(() => fail(new Error("Live connection did not recover.")), DISCONNECT_TIMEOUT_MS);
      } else if (peer.connectionState === "connected") {
        const recovered = disconnectTimer !== undefined;
        clearTimeout(disconnectTimer);
        disconnectTimer = undefined;
        if (recovered && ready && !closing) state("ready");
      }
    });
    // Live requires this channel in the initial offer, not after negotiation.
    channel = peer.createDataChannel("oai-events");
    listen(channel, "message", ({ data }) => {
      let event;
      try {
        event = JSON.parse(data);
        if (!event || typeof event.type !== "string") throw new Error("Missing event type.");
      } catch {
        fail(new Error("Live sent an invalid event."));
        return;
      }
      if (event.type === "session.started") {
        if (typeof event.session?.id !== "string" || event.session.id !== sessionId) {
          fail(new Error("Live session ID did not match the backend session."));
          return;
        }
        if (!ready) {
          ready = true;
          clearTimeout(startTimer);
          resolveStarted();
          state("ready");
        }
      } else if (event.type === "error" && !ready) {
        fail(new Error("Live rejected session startup."));
      }
      try {
        onEvent(event);
      } finally {
        if (event.type === "session.closed") {
          cleanup({ finalized: true, reason: event.reason, usage: event.usage });
        }
      }
    });
    listen(channel, "close", () => fail(new Error("Live data channel closed without session.closed.")));
    listen(channel, "error", () => fail(new Error("Live data channel failed.")));

    if (outputDeviceId !== "") await setOutputDevice(outputDeviceId);
    pending.signal.throwIfAborted();
    const offer = await peer.createOffer();
    pending.signal.throwIfAborted();
    await peer.setLocalDescription(offer);
    await waitForIce(peer, pending.signal);
    const sdp = peer.localDescription?.sdp;
    if (!sdp) throw new Error("Missing local SDP offer.");
    const response = await fetch("/api/live/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp }),
      signal: pending.signal,
    });
    if (!response.ok) throw new Error(`Live session request failed (HTTP ${response.status}).`);
    const result = await response.json();
    pending.signal.throwIfAborted();
    if (typeof result.session?.id !== "string" || !result.session.id ||
        result.transport?.type !== "webrtc" || typeof result.transport.sdp !== "string" || !result.transport.sdp) {
      throw new Error("Backend returned an invalid Live session or WebRTC answer.");
    }
    sessionId = result.session.id;
    await peer.setRemoteDescription({ type: "answer", sdp: result.transport.sdp });
    await started;
    if (disposed || closing) throw new Error("Live closed during startup.");
    return {
      sessionId, send, setInputEnabled, setOutputMuted, setOutputDevice, close,
      get outputDeviceId() { return audio.sinkId ?? ""; },
    };
  } catch (error) {
    fail(error);
    throw error;
  }
}
