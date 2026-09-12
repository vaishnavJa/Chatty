import { Video } from "@remotion/media";
import { ALL_FORMATS, Input, UrlSource } from "mediabunny";
import {
  AbsoluteFill,
  Sequence,
  staticFile,
  type CalculateMetadataFunction,
} from "remotion";
import { FPS, Intro, INTRO_FRAMES } from "./Intro";

type DemoProps = {
  recording: string;
  startSeconds: number;
  endSeconds: number;
  recordingFrames: number;
  sound: boolean;
};

export const calculateDemoMetadata: CalculateMetadataFunction<
  DemoProps
> = async ({ props, isRendering }) => {
  if (!props.recording) {
    if (isRendering)
      throw new Error(
        "No meeting recording. Run npm run render:demo -- <recording-path> first, or render ChattyIntro.",
      );
    return { durationInFrames: INTRO_FRAMES, props };
  }
  const input = new Input({
    formats: ALL_FORMATS,
    source: new UrlSource(staticFile(props.recording)),
  });
  let duration: number;
  try {
    duration = await input.computeDuration();
  } finally {
    input.dispose();
  }
  const end = props.endSeconds || duration;
  if (
    !Number.isFinite(props.startSeconds) ||
    !Number.isFinite(end) ||
    props.startSeconds < 0 ||
    end <= props.startSeconds ||
    end > duration + 1 / FPS
  ) {
    throw new Error(
      `Invalid meeting trim: ${props.startSeconds}–${end}s; recording is ${duration.toFixed(2)}s.`,
    );
  }
  const startFrame = Math.round(props.startSeconds * FPS);
  const recordingFrames = Math.max(1, Math.ceil(end * FPS) - startFrame);
  return {
    durationInFrames: INTRO_FRAMES + recordingFrames,
    props: { ...props, recordingFrames },
  };
};

export const Demo: React.FC<DemoProps> = ({
  recording,
  startSeconds,
  recordingFrames,
  sound,
}) => (
  <AbsoluteFill style={{ background: "#111512" }}>
    <Sequence durationInFrames={INTRO_FRAMES}>
      <Intro sound={sound} />
    </Sequence>
    {recording && (
      <Sequence from={INTRO_FRAMES} durationInFrames={recordingFrames}>
        <Video
          src={staticFile(recording)}
          trimBefore={Math.round(startSeconds * FPS)}
          objectFit="contain"
          style={{ width: "100%", height: "100%" }}
        />
      </Sequence>
    )}
  </AbsoluteFill>
);
