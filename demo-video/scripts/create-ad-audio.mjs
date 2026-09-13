import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const script = JSON.parse(
  readFileSync(resolve(root, "src/ad-script.json"), "utf8"),
);
const localVoice = process.argv.includes("--local-voice");
const scratch = resolve(
  root,
  localVoice ? "out/ad-audio-local" : "out/ad-audio",
);
const destination = resolve(root, "public/audio/ad");
mkdirSync(scratch, { recursive: true });
mkdirSync(destination, { recursive: true });

// Only the key is read from the local ignored environment file. It is never
// printed, passed in process arguments, or included in generated artifacts.
function apiKey() {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY;
  const envPath = resolve(root, "../.env");
  if (!existsSync(envPath))
    throw new Error(
      "Set OPENAI_API_KEY or configure the repository's ignored .env file.",
    );
  const match = readFileSync(envPath, "utf8").match(
    /^\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*$/m,
  );
  const value = match?.[1]?.replace(/^['"]|['"]$/g, "");
  if (!value)
    throw new Error("OPENAI_API_KEY is missing from the local environment.");
  return value;
}

function command(program, args) {
  const result = spawnSync(program, args, {
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.status !== 0)
    throw new Error(
      `${program} failed: ${result.stderr?.slice(-1000) || result.error?.message}`,
    );
  return result.stdout;
}

const timings = [];
for (const part of script) {
  const raw = resolve(scratch, `narration-${part.id}.wav`);
  if (!existsSync(raw) && localVoice) {
    const aiff = resolve(scratch, `narration-${part.id}.aiff`);
    command("say", ["-v", "Samantha", "-r", "180", "-o", aiff, part.text]);
    command("ffmpeg", [
      "-y",
      "-v",
      "error",
      "-i",
      aiff,
      "-ar",
      "48000",
      "-ac",
      "1",
      raw,
    ]);
  } else if (!existsSync(raw)) {
    const response = await fetch("https://api.openai.com/v1/audio/speech", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-4o-mini-tts",
        voice: "marin",
        input: part.text,
        instructions:
          "Narrate a polished sixty-second product film. Warm, clear, confident and conversational English. A natural, gently energetic female storyteller, never a sales announcer. Light emphasis on Chatty. Keep the pace brisk, about 165 words per minute, with short intentional pauses. Read only the supplied text. Do not add any words.",
        response_format: "wav",
      }),
      signal: AbortSignal.timeout(90000),
    });
    if (!response.ok)
      throw new Error(
        `Speech generation failed with HTTP ${response.status}; no response body or credentials logged.`,
      );
    writeFileSync(raw, Buffer.from(await response.arrayBuffer()));
  }
  const seconds = Number(
    command("ffprobe", [
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      raw,
    ]).trim(),
  );
  const available = part.duration - 0.65;
  const tempo = Math.max(1, seconds / available);
  if (tempo > 1.22)
    throw new Error(
      `Narration ${part.id} is too long for its scene (${seconds.toFixed(2)}s). Shorten the script or regenerate it; don't rush the voice.`,
    );
  const prepared = resolve(scratch, `fit-${part.id}.wav`);
  const normalized = resolve(scratch, `normalized-${part.id}.wav`);
  // Normalize to a fresh WAV first: loudnorm changes filter timestamps, which
  // must not shorten the following scene padding when everything is chained.
  command("ffmpeg", [
    "-y",
    "-v",
    "error",
    "-i",
    raw,
    "-af",
    `atempo=${tempo},loudnorm=I=-17:TP=-2:LRA=7`,
    "-ar",
    "48000",
    "-ac",
    "2",
    normalized,
  ]);
  command("ffmpeg", [
    "-y",
    "-v",
    "error",
    "-i",
    normalized,
    "-af",
    "adelay=300|300,apad",
    "-t",
    String(part.duration),
    "-ar",
    "48000",
    "-ac",
    "2",
    prepared,
  ]);
  const fittedSeconds = Number(
    command("ffprobe", [
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "csv=p=0",
      prepared,
    ]).trim(),
  );
  if (Math.abs(fittedSeconds - part.duration) > 1 / 48000)
    throw new Error(
      `Scene ${part.id} audio duration mismatch: ${fittedSeconds}s, expected ${part.duration}s.`,
    );
  timings.push({
    id: part.id,
    rawSeconds: seconds,
    tempo,
    spokenStart: part.start + 0.3,
    spokenEnd: part.start + 0.3 + seconds / tempo,
  });
  console.log(
    `Prepared scene ${part.id}: ${seconds.toFixed(2)}s, tempo ${tempo.toFixed(3)}`,
  );
}

// Original, deterministic instrumental score: soft electric-piano harmonics,
// restrained plucks, warm bass, and small transition chimes. No sampled music.
const sr = 48000;
const duration = 60;
const samples = sr * duration;
const left = new Float32Array(samples);
const right = new Float32Array(samples);
const tau = Math.PI * 2;
const hz = (midi) => 440 * 2 ** ((midi - 69) / 12);
function tone(start, length, midi, gain, pan = 0, pluck = false) {
  const first = Math.floor(start * sr);
  const frequency = hz(midi);
  const count = Math.min(Math.floor(length * sr), samples - first);
  for (let i = 0; i < count; i++) {
    const t = i / sr;
    const envelope =
      Math.min(t / (pluck ? 0.009 : 0.28), 1) *
      Math.min((length - t) / (pluck ? 0.25 : 0.65), 1) *
      Math.exp(-t * (pluck ? 3.2 : 0.38));
    const s =
      (Math.sin(tau * frequency * t) +
        0.2 * Math.sin(tau * frequency * 2 * t) +
        0.055 * Math.sin(tau * frequency * 3 * t)) *
      envelope *
      gain;
    left[first + i] += s * Math.sqrt((1 - pan) / 2);
    right[first + i] += s * Math.sqrt((1 + pan) / 2);
  }
}
const chords = [
  [48, 55, 60, 64, 67],
  [45, 52, 57, 60, 64],
  [41, 48, 53, 57, 60],
  [43, 50, 55, 59, 62],
];
for (let beat = 0; beat < 100; beat++) {
  const at = beat * 0.6;
  const chord = chords[Math.floor(beat / 8) % chords.length];
  if (beat % 8 === 0)
    chord.slice(1).forEach((m, i) => tone(at, 5.1, m, 0.015, (i - 1.5) * 0.3));
  if (beat % 4 === 0) tone(at, 2.3, chord[0], 0.024, 0);
  if (beat > 9 && beat < 86 && beat % 2 === 0)
    tone(
      at + 0.03,
      1.2,
      chord[2 + (Math.floor(beat / 2) % 3)] + 12,
      0.013,
      Math.sin(beat) * 0.6,
      true,
    );
}
for (const at of [6, 13, 21, 29, 38, 45, 52]) {
  tone(at + 0.01, 1, 79, 0.025, -0.15, true);
  tone(at + 0.12, 1.1, 84, 0.015, 0.2, true);
}
tone(57.6, 2.4, 72, 0.035, -0.2);
tone(57.65, 2.3, 76, 0.018, 0.25);
const wav = Buffer.alloc(44 + samples * 4);
wav.write("RIFF", 0);
wav.writeUInt32LE(wav.length - 8, 4);
wav.write("WAVEfmt ", 8);
wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20);
wav.writeUInt16LE(2, 22);
wav.writeUInt32LE(sr, 24);
wav.writeUInt32LE(sr * 4, 28);
wav.writeUInt16LE(4, 32);
wav.writeUInt16LE(16, 34);
wav.write("data", 36);
wav.writeUInt32LE(samples * 4, 40);
for (let i = 0; i < samples; i++) {
  const fade = Math.min(i / sr / 1.1, 1, (duration - i / sr) / 1.6);
  wav.writeInt16LE(
    Math.round(Math.max(-1, Math.min(1, left[i] * fade)) * 32767),
    44 + i * 4,
  );
  wav.writeInt16LE(
    Math.round(Math.max(-1, Math.min(1, right[i] * fade)) * 32767),
    46 + i * 4,
  );
}
writeFileSync(resolve(scratch, "score.wav"), wav);

const inputs = script.flatMap((p) => [
  "-i",
  resolve(scratch, `fit-${p.id}.wav`),
]);
const concat =
  script.map((_, i) => `[${i}:a]`).join("") +
  `concat=n=${script.length}:v=0:a=1[voice];[voice][${script.length}:a]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=8[out]`;
command("ffmpeg", [
  "-y",
  "-v",
  "error",
  ...inputs,
  "-i",
  resolve(scratch, "score.wav"),
  "-filter_complex",
  concat,
  "-map",
  "[out]",
  "-ar",
  "48000",
  "-ac",
  "2",
  resolve(scratch, "mix-normalized.wav"),
]);
command("ffmpeg", [
  "-y",
  "-v",
  "error",
  "-i",
  resolve(scratch, "mix-normalized.wav"),
  "-af",
  "apad",
  "-t",
  "60",
  "-ar",
  "48000",
  "-ac",
  "2",
  resolve(destination, "chatty-ad-mix.wav"),
]);
const finalSeconds = Number(
  command("ffprobe", [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "csv=p=0",
    resolve(destination, "chatty-ad-mix.wav"),
  ]).trim(),
);
if (finalSeconds !== 60)
  throw new Error(
    `Final audio must be exactly 60 seconds, got ${finalSeconds}.`,
  );
writeFileSync(
  resolve(root, "src/ad-timings.json"),
  JSON.stringify(timings, null, 2) + "\n",
);

const stamp = (sec) => {
  const ms = Math.round(sec * 1000);
  return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`;
};
writeFileSync(
  resolve(root, "out/chatty-ad-60s.srt"),
  script
    .map(
      (part, i) =>
        `${i + 1}\n${stamp(part.start + 0.3)} --> ${stamp(timings[i].spokenEnd)}\n${part.text}\n`,
    )
    .join("\n"),
);
writeFileSync(
  resolve(root, "out/chatty-ad-script.txt"),
  script.map((part) => `${stamp(part.start)}\n${part.text}`).join("\n\n") +
    `\n\n${localVoice ? "Narration synthesized locally with macOS (Samantha)." : "AI-generated narration by OpenAI (marin)."} Original synthesized instrumental music. Product scenes are illustrative, with fictional people and an example ticketing workflow; they are not a live recording.\n`,
);
console.log("Created 60-second mix, captions and narration script.");
