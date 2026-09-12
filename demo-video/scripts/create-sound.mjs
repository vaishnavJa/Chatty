import { mkdirSync, writeFileSync } from "node:fs";

const sampleRate = 48000;
const samples = sampleRate * 10;
const data = new Float64Array(samples);
const tau = 2 * Math.PI;
const note = (start, duration, frequency, gain, bright = false) => {
  const first = Math.round(start * sampleRate);
  for (let i = 0; i < duration * sampleRate && first + i < samples; i++) {
    const t = i / sampleRate;
    const envelope =
      Math.min(t / 0.025, 1) *
      Math.exp(-t / (duration * 0.24)) *
      Math.min((duration - t) / 0.12, 1);
    const tone =
      Math.sin(tau * frequency * t) +
      (bright ? 0.18 * Math.sin(tau * frequency * 2 * t) : 0);
    data[first + i] += tone * envelope * gain;
  }
};

// Original, deterministic sound: no sampled recordings.
for (const [start, frequencies] of [
  [0.1, [164.81, 246.94, 329.63]],
  [3, [146.83, 220, 293.66]],
  [6.7, [196, 293.66, 392]],
]) {
  frequencies.forEach((frequency, index) =>
    note(start + index * 0.085, 2.4, frequency, 0.055, true),
  );
}
for (const start of [0.9, 1.65, 3.5, 3.8, 4.1, 6.78, 8.05])
  note(start, 0.16, 784, 0.022);
note(6.7, 1.4, 65.41, 0.12);

let peak = 0;
for (const sample of data) peak = Math.max(peak, Math.abs(sample));
const pcm = Buffer.alloc(samples * 2);
for (let i = 0; i < samples; i++)
  pcm.writeInt16LE(Math.round((data[i] / peak) * 0.38 * 32767), i * 2);
const header = Buffer.alloc(44);
header.write("RIFF", 0);
header.writeUInt32LE(36 + pcm.length, 4);
header.write("WAVEfmt ", 8);
header.writeUInt32LE(16, 16);
header.writeUInt16LE(1, 20);
header.writeUInt16LE(1, 22);
header.writeUInt32LE(sampleRate, 24);
header.writeUInt32LE(sampleRate * 2, 28);
header.writeUInt16LE(2, 32);
header.writeUInt16LE(16, 34);
header.write("data", 36);
header.writeUInt32LE(pcm.length, 40);
mkdirSync("public/audio", { recursive: true });
writeFileSync("public/audio/intro.wav", Buffer.concat([header, pcm]));
console.log("Created original 10-second intro sound.");
