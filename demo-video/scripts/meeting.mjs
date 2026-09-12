import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
const render = args[0] === "--render";
if (render) args.shift();
const [source, start = "0", end = "0"] = args;
if (args.length > 3 || (!source && !existsSync("meeting.props.json"))) {
  console.error(
    'Usage: npm run render:demo -- "C:/recordings/meeting.mp4" [start-seconds] [end-seconds]',
  );
  process.exit(1);
}
if (source) {
  const recordingPath = path.resolve(source);
  if (!existsSync(recordingPath))
    throw new Error(`Recording not found: ${recordingPath}`);
  const startSeconds = Number(start);
  const endSeconds = Number(end);
  if (
    !Number.isFinite(startSeconds) ||
    !Number.isFinite(endSeconds) ||
    startSeconds < 0 ||
    endSeconds < 0 ||
    (endSeconds > 0 && endSeconds <= startSeconds)
  ) {
    throw new Error(
      "Use non-negative start/end seconds, with end after start. Omit end to use the full remaining recording.",
    );
  }
  const extension = path.extname(recordingPath).toLowerCase();
  if (![".mp4", ".mov", ".webm", ".mkv", ".m4v"].includes(extension))
    throw new Error("Use an MP4, MOV, WebM, MKV, or M4V recording.");
  const recording = `meeting/recording${extension}`;
  const destination = path.resolve("public", recording);
  mkdirSync(path.dirname(destination), { recursive: true });
  if (recordingPath !== destination) copyFileSync(recordingPath, destination);
  writeFileSync(
    "meeting.props.json",
    JSON.stringify(
      { recording, startSeconds, endSeconds, recordingFrames: 0, sound: true },
      null,
      2,
    ) + "\n",
  );
  console.log(
    "Meeting prepared. Original file is untouched; local copy and props are ignored by Git.",
  );
}
if (render) {
  const cliPackage = require.resolve("@remotion/cli/package.json");
  const cli = path.join(
    path.dirname(cliPackage),
    JSON.parse(readFileSync(cliPackage, "utf8")).bin.remotion,
  );
  const result = spawnSync(
    process.execPath,
    [
      cli,
      "render",
      "ChattyDemo",
      "out/chatty-demo.mp4",
      "--props=meeting.props.json",
      "--codec=h264",
      "--crf=16",
    ],
    { stdio: "inherit" },
  );
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}
