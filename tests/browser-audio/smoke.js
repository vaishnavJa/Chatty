import { captureInput } from "../../web/media.js";

const start = document.querySelector("#start");
const stop = document.querySelector("#stop");
const tone = document.querySelector("#tone");
const status = document.querySelector("#status");
const level = document.querySelector("#level");
let capture;
let inputContext;
let toneContext;
let frame;
let generation = 0;

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
  const requested = captureInput(document.querySelector("#source").value);
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
    const measure = () => {
      analyser.getFloatTimeDomainData(samples);
      level.value = Math.min(1, Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length) * 5);
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
    const oscillator = toneContext.createOscillator();
    const gain = toneContext.createGain();
    oscillator.frequency.value = 440;
    gain.gain.setValueAtTime(0, toneContext.currentTime);
    gain.gain.linearRampToValueAtTime(0.08, toneContext.currentTime + 0.03);
    gain.gain.linearRampToValueAtTime(0, toneContext.currentTime + 0.8);
    oscillator.connect(gain).connect(toneContext.destination);
    oscillator.start();
    oscillator.stop(toneContext.currentTime + 0.8);
    oscillator.addEventListener("ended", () => { toneContext.close(); tone.disabled = false; }, { once: true });
  } catch (error) {
    toneContext?.close();
    tone.disabled = false;
    status.textContent = error.message;
  }
});

window.addEventListener("pagehide", () => { stopCapture(); toneContext?.close(); });
