/** Enumerate only outputs already exposed by the browser; starts no capture. */
export async function listAudioOutputs() {
  const devices = globalThis.navigator?.mediaDevices;
  if (!devices?.enumerateDevices) throw new Error("Audio device selection is unavailable. Use Chrome on localhost or HTTPS.");
  return (await devices.enumerateDevices())
    .filter((device) => device.kind === "audiooutput")
    .map(({ deviceId, label }) => ({ deviceId, label }));
}

/** Call from an explicit permission button; releases the temporary mic immediately. */
export async function requestAudioOutputs() {
  const devices = globalThis.navigator?.mediaDevices;
  if (!devices?.getUserMedia) throw new Error("Audio device permission is unavailable. Use Chrome on localhost or HTTPS.");
  const permission = await devices.getUserMedia({ audio: true, video: false });
  try {
    return await listAudioOutputs();
  } finally {
    permission.getTracks().forEach((track) => track.stop());
  }
}

/** Request capture only from a click/tap handler; browsers require user activation. */
export async function captureInput(source, { keepVideo = false } = {}) {
  if (source !== "microphone" && source !== "meeting-tab") {
    throw new TypeError('Audio source must be "microphone" or "meeting-tab".');
  }
  const devices = globalThis.navigator?.mediaDevices;
  const method = source === "meeting-tab" ? "getDisplayMedia" : "getUserMedia";
  if (!devices?.[method]) {
    throw new Error("Audio capture is unavailable. Use Chrome on localhost or HTTPS.");
  }

  // Display capture requires video permission, even when only audio is needed.
  // These are chooser hints: the person still selects the Meet tab explicitly.
  const stream = await devices[method](source === "meeting-tab" ? {
    video: { displaySurface: "browser" },
    audio: { suppressLocalAudioPlayback: false },
    preferCurrentTab: false,
    selfBrowserSurface: "exclude",
    systemAudio: "exclude",
    monitorTypeSurfaces: "exclude",
    surfaceSwitching: "exclude",
  } : {
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    video: false,
  });
  const tracks = stream.getTracks();
  let videoStream;
  let stopped = false;
  function stop() {
    if (stopped) return;
    stopped = true;
    globalThis.removeEventListener?.("pagehide", stop);
    stream.removeEventListener("inactive", stop);
    for (const track of tracks) {
      track.removeEventListener("ended", stop);
      track.stop();
    }
  }

  try {
    if (!stream.getAudioTracks().some((track) => track.readyState === "live")) {
      throw new Error(source === "meeting-tab"
        ? 'No tab audio received. Select the Meet tab and enable "Share tab audio".'
        : "No live microphone audio track was returned.");
    }
    const surface = stream.getVideoTracks()[0]?.getSettings().displaySurface;
    if (source === "meeting-tab" && surface && surface !== "browser") {
      throw new Error("Select a browser tab for meeting audio, not a window or screen.");
    }
    const videoTracks = stream.getVideoTracks();
    if (source === "meeting-tab" && keepVideo) videoStream = new MediaStream(videoTracks);
    for (const track of videoTracks) {
      stream.removeTrack(track);
      if (videoStream) track.addEventListener("ended", stop);
      else track.stop();
    }
    for (const track of stream.getAudioTracks()) track.addEventListener("ended", stop);
    stream.addEventListener("inactive", stop);
    globalThis.addEventListener?.("pagehide", stop, { once: true });
    return { stream, videoStream, stop };
  } catch (error) {
    stop();
    throw error;
  }
}
