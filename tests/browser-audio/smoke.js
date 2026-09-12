import { captureInput, requestAudioOutputs } from "../../web/media.js";

const start = document.querySelector("#start");
const stop = document.querySelector("#stop");
const tone = document.querySelector("#tone");
const status = document.querySelector("#status");
const level = document.querySelector("#level");
const output = document.querySelector("#output");
const inputDevice = document.querySelector("#input-device");
const peak = document.querySelector("#peak");
let capture;
let inputContext;
let toneContext;
let toneAudio;
let frame;
let generation = 0;

async function refreshDevices(requestPermission = false) {
  try {
    if (requestPermission) await requestAudioOutputs();
    const devices = await navigator.mediaDevices.enumerateDevices();
    for (const [select, kind, label] of [[output, "audiooutput", "System default (local test)"], [inputDevice, "audioinput", "Default microphone"]]) {
      const selected = select.value;
      select.replaceChildren(new Option(label, ""));
      for (const device of devices.filter((item) => item.kind === kind && item.deviceId)) {
        select.add(new Option(device.label || `${kind} (allow permission to see name)`, device.deviceId));
      }
      if ([...select.options].some((option) => option.value === selected)) select.value = selected;
    }
    status.textContent = "Audio devices refreshed. Select an output and, for a local cable check, the matching input.";
  } catch (error) {
    status.textContent = error.message;
  }
}

document.querySelector("#devices").addEventListener("click", () => refreshDevices());
document.querySelector("#permission").addEventListener("click", () => refreshDevices(true));

function stopTone() {
  toneAudio?.pause();
  toneAudio?.srcObject?.getTracks().forEach((track) => track.stop());
  if (toneAudio) toneAudio.srcObject = null;
  toneAudio = undefined;
  toneContext?.close();
  toneContext = undefined;
  tone.disabled = false;
}

function stopCapture() {
  generation++;
  cancelAnimationFrame(frame);
  capture?.stop();
  capture = undefined;
  inputContext?.close();
  inputContext = undefined;
  level.value = 0;
  start.disabled = false;
  stop.disabled = true;
  status.textContent = "Capture stopped.";
}

start.addEventListener("click", async () => {
  const attempt = ++generation;
  start.disabled = true;
  stop.disabled = false;
  status.textContent = "Choose the audio source and allow sharing.";
  // Start the chooser directly within this user gesture.
  const source = document.querySelector("#source").value;
  const requested = source === "microphone" && inputDevice.value
    ? navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: inputDevice.value }, echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false })
      .then((stream) => ({ stream, stop: () => stream.getTracks().forEach((track) => track.stop()) }))
    : captureInput(source);
  try {
    const selected = await requested;
    if (attempt !== generation) { selected.stop(); return; }
    capture = selected;
    inputContext = new AudioContext();
    await inputContext.resume();
    if (attempt !== generation) return;
    const analyser = inputContext.createAnalyser();
    analyser.fftSize = 512;
    inputContext.createMediaStreamSource(capture.stream).connect(analyser);
    // Deliberately never connect input to speakers: that would create feedback.
    const samples = new Float32Array(analyser.fftSize);
    let peakLevel = 0;
    const measure = () => {
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
      level.value = Math.min(1, rms * 5);
      peakLevel = Math.max(peakLevel, rms);
      peak.textContent = `Peak level: ${peakLevel.toFixed(4)}`;
      frame = requestAnimationFrame(measure);
    };
    measure();
    for (const track of capture.stream.getAudioTracks()) track.addEventListener("ended", stopCapture, { once: true });
    status.textContent = `Capturing ${capture.stream.getAudioTracks().length} audio track(s). Ask someone on the second device to speak.`;
  } catch (error) {
    if (attempt !== generation) return;
    stopCapture();
    status.textContent = error.message;
  }
});

stop.addEventListener("click", stopCapture);
tone.addEventListener("click", async () => {
  tone.disabled = true;
  try {
    toneContext = new AudioContext();
    await toneContext.resume();
    const destination = toneContext.createMediaStreamDestination();
    toneAudio = new Audio();
    toneAudio.srcObject = destination.stream;
    if (output.value) {
      if (typeof toneAudio.setSinkId !== "function") throw new Error("This browser cannot select the test output device.");
      await toneAudio.setSinkId(output.value);
    }
    await toneAudio.play();
    const oscillator = toneContext.createOscillator();
    const gain = toneContext.createGain();
    oscillator.frequency.value = 440;
    gain.gain.setValueAtTime(0, toneContext.currentTime);
    gain.gain.linearRampToValueAtTime(0.08, toneContext.currentTime + 0.03);
    gain.gain.linearRampToValueAtTime(0, toneContext.currentTime + 0.8);
    oscillator.connect(gain).connect(destination);
    oscillator.start();
    oscillator.stop(toneContext.currentTime + 0.8);
    oscillator.addEventListener("ended", stopTone, { once: true });
  } catch (error) {
    stopTone();
    status.textContent = error.message;
  }
});

window.addEventListener("pagehide", () => { stopCapture(); stopTone(); });
