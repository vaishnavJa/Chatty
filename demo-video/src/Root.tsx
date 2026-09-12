import "./index.css";
import { Composition } from "remotion";
import { FPS, Intro, INTRO_FRAMES } from "./Intro";
import { Demo, calculateDemoMetadata } from "./Meeting";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ChattyIntro"
        component={Intro}
        durationInFrames={INTRO_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ sound: true }}
      />
      <Composition
        id="ChattyDemo"
        component={Demo}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{
          recording: "",
          startSeconds: 0,
          endSeconds: 0,
          recordingFrames: 0,
          sound: true,
        }}
        calculateMetadata={calculateDemoMetadata}
      />
    </>
  );
};
