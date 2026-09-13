import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const destination = resolve(root, "out/chatty-ad-60s.mp4");
function command(program, args) {
  const result = spawnSync(program, args, {
    encoding: "utf8",
    maxBuffer: 2 * 1024 * 1024,
  });
  if (result.status !== 0)
    throw new Error(
      `${program} failed: ${result.stderr || result.error?.message}`,
    );
  return result.stdout;
}

// Copy the rendered H.264 frames without another lossy encode. Re-mux the
// lossless mix with an exact edit duration to remove AAC frame-padding overrun.
command("ffmpeg", [
  "-y",
  "-v",
  "error",
  "-i",
  resolve(root, "out/chatty-ad-render.mp4"),
  "-i",
  resolve(root, "public/audio/ad/chatty-ad-mix.wav"),
  "-map",
  "0:v:0",
  "-map",
  "1:a:0",
  "-c:v",
  "copy",
  "-c:a",
  "aac",
  "-b:a",
  "192k",
  "-t",
  "60",
  "-movflags",
  "+faststart",
  destination,
]);
const metadata = JSON.parse(
  command("ffprobe", [
    "-v",
    "error",
    "-show_entries",
    "format=duration:stream=codec_type,nb_frames,width,height,r_frame_rate,duration",
    "-of",
    "json",
    destination,
  ]),
);
const video = metadata.streams.find((s) => s.codec_type === "video");
if (
  metadata.format.duration !== "60.000000" ||
  video.nb_frames !== "1800" ||
  video.width !== 1920 ||
  video.height !== 1080 ||
  video.r_frame_rate !== "30/1"
)
  throw new Error(
    "The advertisement export must be exactly 60 seconds, 1,800 frames at 1920x1080 / 30 fps.",
  );
console.log(
  "Exported out/chatty-ad-60s.mp4: 60.000 seconds, 1,800 frames, 1920x1080, 30 fps.",
);
