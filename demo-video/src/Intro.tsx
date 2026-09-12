import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";
import type { CSSProperties } from "react";

loadFont({
  family: "Geist",
  url: staticFile("fonts/geist.woff2"),
  weight: "100 900",
});

export const FPS = 30;
export const INTRO_FRAMES = 300;
const ink = "#111512";
const paper = "#f1f0e8";
const orange = "#ff7146";
const muted = "#969e94";
const ease = Easing.bezier(0.16, 1, 0.3, 1);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const enter = (frame: number, delay = 0, length = 22) =>
  interpolate(frame, [delay, delay + length], [0, 1], {
    ...clamp,
    easing: ease,
  });
const label: CSSProperties = {
  fontSize: 22,
  fontWeight: 500,
  letterSpacing: 3,
  textTransform: "uppercase",
};

const Reveal: React.FC<{
  children: React.ReactNode;
  delay?: number;
  style?: CSSProperties;
}> = ({ children, delay = 0, style }) => {
  const progress = enter(useCurrentFrame(), delay);
  return (
    <div
      style={{
        opacity: progress,
        transform: `translateY(${(1 - progress) * 54}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const Mark: React.FC<{ size?: number; dark?: boolean }> = ({
  size = 52,
  dark = false,
}) => (
  <svg width={size} height={size} viewBox="0 0 80 80" fill="none">
    <path
      d="M16 12H64C70.6 12 76 17.4 76 24V52C76 58.6 70.6 64 64 64H36L17 77V64H16C9.4 64 4 58.6 4 52V24C4 17.4 9.4 12 16 12Z"
      fill={dark ? ink : orange}
    />
    {[0, 1, 2].map((i) => (
      <rect
        key={i}
        x={22 + i * 14}
        y={i === 1 ? 23 : 30}
        width={8}
        height={i === 1 ? 30 : 16}
        rx={4}
        fill={dark ? paper : ink}
      />
    ))}
  </svg>
);

const Wave: React.FC<{ frame: number }> = ({ frame }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 7, height: 124 }}>
    {Array.from({ length: 37 }, (_, i) => {
      const envelope = Math.sin((i / 36) * Math.PI);
      const height =
        8 + envelope * (25 + 70 * Math.abs(Math.sin(frame * 0.11 - i * 0.65)));
      return (
        <div
          key={i}
          style={{
            width: 7,
            height,
            borderRadius: 9,
            background: orange,
            opacity: 0.45 + envelope * 0.55,
          }}
        />
      );
    })}
  </div>
);

const Opening = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: paper, color: ink }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(#11151208 1px, transparent 1px), linear-gradient(90deg, #11151208 1px, transparent 1px)",
          backgroundSize: "96px 96px",
        }}
      />
      <div style={{ position: "absolute", left: 112, top: 242 }}>
        <Reveal>
          <div style={{ ...label, color: "#656d63" }}>A familiar moment</div>
        </Reveal>
        <Reveal delay={3}>
          <div
            style={{
              fontSize: 133,
              lineHeight: 0.99,
              fontWeight: 600,
              letterSpacing: -8,
              marginTop: 36,
            }}
          >
            Your team
            <br />
            is talking.
          </div>
        </Reveal>
        <Reveal delay={16}>
          <div style={{ fontSize: 32, color: "#656d63", marginTop: 36 }}>
            The answers are somewhere else.
          </div>
        </Reveal>
      </div>
      <Reveal
        delay={9}
        style={{ position: "absolute", right: 112, top: 264, width: 584 }}
      >
        <div
          style={{
            background: ink,
            color: paper,
            padding: "40px 44px",
            borderRadius: "34px 34px 8px 34px",
            transform: "rotate(-3deg)",
            boxShadow: "0 22px 50px #11151212",
          }}
        >
          <div
            style={{ ...label, color: muted, fontSize: 17, marginBottom: 24 }}
          >
            In the meeting
          </div>
          <div style={{ fontSize: 43, letterSpacing: -1.8 }}>
            “What changed?”
          </div>
          <div style={{ marginTop: 16 }}>
            <Wave frame={frame} />
          </div>
        </div>
        <div
          style={{
            opacity: enter(frame, 24),
            transform: `translateY(${(1 - enter(frame, 24)) * 28}px) rotate(3deg)`,
            background: orange,
            padding: "28px 36px",
            margin: "28px 0 0 90px",
            borderRadius: "8px 26px 26px 26px",
            fontSize: 42,
            letterSpacing: -1.8,
          }}
        >
          “What’s next?”
        </div>
      </Reveal>
      <div
        style={{
          ...label,
          color: "#656d63",
          position: "absolute",
          left: 112,
          bottom: 82,
          fontSize: 18,
        }}
      >
        Less searching. More conversation.
      </div>
    </AbsoluteFill>
  );
};

const ProjectContext = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: ink, color: paper }}>
      <Reveal style={{ position: "absolute", left: 112, top: 252 }}>
        <div style={{ ...label, color: orange }}>Bring the context in</div>
        <div
          style={{
            fontSize: 117,
            lineHeight: 1.02,
            fontWeight: 560,
            letterSpacing: -7,
            marginTop: 36,
          }}
        >
          Your project.
          <br />
          In the
          <br />
          <span style={{ color: orange }}>conversation.</span>
        </div>
      </Reveal>
      <div style={{ position: "absolute", left: 1090, top: 256, width: 710 }}>
        <Reveal delay={7}>
          <div style={{ ...label, color: muted, marginBottom: 34 }}>
            Connected to GitHub
          </div>
        </Reveal>
        {["Commits", "Pull requests", "Issues"].map((source, i) => (
          <Reveal key={source} delay={10 + i * 9}>
            <div
              style={{
                borderTop: "1px solid #3b443b",
                padding: "25px 0",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
                <span style={{ color: orange, fontSize: 20 }}>0{i + 1}</span>
                <span style={{ fontSize: 46, letterSpacing: -2 }}>
                  {source}
                </span>
              </div>
              <span style={{ color: orange, fontSize: 38 }}>↗</span>
            </div>
          </Reveal>
        ))}
        <Reveal
          delay={38}
          style={{ borderTop: "1px solid #3b443b", paddingTop: 28 }}
        >
          <Wave frame={frame} />
          <div style={{ color: muted, fontSize: 25 }}>
            Ask in the flow of the meeting.
          </div>
        </Reveal>
      </div>
    </AbsoluteFill>
  );
};

const MeetChatty = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: orange,
        color: ink,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Reveal
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          marginTop: -40,
        }}
      >
        <Mark size={80} dark />
        <span style={{ ...label, fontSize: 24 }}>
          Your AI meeting companion
        </span>
      </Reveal>
      <Reveal delay={5}>
        <div
          style={{
            fontSize: 230,
            fontWeight: 650,
            letterSpacing: -14,
            lineHeight: 1.15,
            marginTop: 24,
          }}
        >
          Meet Chatty.
        </div>
      </Reveal>
      <Reveal delay={14}>
        <div style={{ fontSize: 38, letterSpacing: -0.8, marginTop: 28 }}>
          Keep the conversation moving.
        </div>
      </Reveal>
      <Reveal
        delay={39}
        style={{
          position: "absolute",
          bottom: 119,
          display: "flex",
          alignItems: "center",
          gap: 19,
        }}
      >
        <span
          style={{
            width: 11,
            height: 11,
            background: ink,
            borderRadius: "50%",
          }}
        />
        <span style={{ ...label, fontSize: 20 }}>Let’s join the meeting</span>
        <span style={{ fontSize: 30 }}>→</span>
      </Reveal>
      <div
        style={{
          position: "absolute",
          left: 0,
          bottom: 0,
          height: 8,
          width: `${interpolate(frame, [0, 98], [0, 100], clamp)}%`,
          background: ink,
        }}
      />
    </AbsoluteFill>
  );
};

export const Intro: React.FC<{ sound?: boolean }> = ({ sound = true }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: ink, fontFamily: "Geist, sans-serif" }}>
      <Sequence durationInFrames={90}>
        <Opening />
      </Sequence>
      <Sequence from={90} durationInFrames={111}>
        <ProjectContext />
      </Sequence>
      <Sequence from={201} durationInFrames={99}>
        <MeetChatty />
      </Sequence>
      {frame < 201 && (
        <div
          style={{
            position: "absolute",
            left: 112,
            right: 112,
            top: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            color: frame < 90 ? ink : paper,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Mark size={46} />
            <span
              style={{ fontSize: 35, fontWeight: 620, letterSpacing: -1.5 }}
            >
              chatty
            </span>
          </div>
          <span style={{ ...label, fontSize: 17, opacity: 0.6 }}>
            From project to conversation
          </span>
        </div>
      )}
      <AbsoluteFill
        style={{
          background: ink,
          opacity: interpolate(frame, [290, 299], [0, 1], clamp),
        }}
      />
      {sound && <Audio src={staticFile("audio/intro.wav")} volume={0.8} />}
    </AbsoluteFill>
  );
};
