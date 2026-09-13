import { BrandMark as Mark } from "./BrandMark";
import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import type { CSSProperties, ReactNode } from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";
import script from "./ad-script.json";
import timings from "./ad-timings.json";

loadFont({
  family: "Geist",
  url: staticFile("fonts/geist.woff2"),
  weight: "100 900",
});

export const AD_FRAMES = 1800;
const ink = "#171b18";
const paper = "#f1f0e8";
const orange = "#ff7146";
const soft = "#a9b1a6";
const green = "#b5d6a5";
const ease = Easing.bezier(0.16, 1, 0.3, 1);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const enter = (frame: number, delay = 0, length = 24) =>
  interpolate(frame, [delay, delay + length], [0, 1], {
    ...clamp,
    easing: ease,
  });
const label: CSSProperties = {
  fontSize: 19,
  fontWeight: 560,
  letterSpacing: 2.4,
  textTransform: "uppercase",
};
const headline: CSSProperties = {
  fontSize: 104,
  fontWeight: 570,
  letterSpacing: -6.7,
  lineHeight: 1.045,
  margin: 0,
};

const Reveal = ({
  children,
  delay = 0,
  style,
}: {
  children: ReactNode;
  delay?: number;
  style?: CSSProperties;
}) => {
  const p = enter(useCurrentFrame(), delay);
  return (
    <div
      style={{
        opacity: p,
        transform: `translateY(${(1 - p) * 40}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const Wave = ({
  quiet = false,
  color = orange,
  width = 520,
}: {
  quiet?: boolean;
  color?: string;
  width?: number;
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        width,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        height: 94,
      }}
    >
      {Array.from({ length: 39 }, (_, i) => {
        const env = Math.sin((i / 38) * Math.PI);
        const height = quiet
          ? 5 + 3 * Math.abs(Math.sin(frame * 0.025 + i / 6))
          : 6 + env * (22 + 62 * Math.abs(Math.sin(frame * 0.14 - i * 0.66)));
        return (
          <div
            key={i}
            style={{
              width: 6,
              height,
              borderRadius: 12,
              background: color,
              opacity: 0.35 + env * 0.65,
            }}
          />
        );
      })}
    </div>
  );
};

const Check = ({ size = 32 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
    <path
      d="M7 16L13 22L25 10"
      stroke="currentColor"
      strokeWidth="2.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
const Pill = ({
  children,
  dark = false,
  accent = false,
}: {
  children: ReactNode;
  dark?: boolean;
  accent?: boolean;
}) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 10,
      padding: "10px 17px",
      borderRadius: 100,
      background: accent ? green : dark ? "#ffffff0b" : "#171b1808",
      border: `1px solid ${accent ? "transparent" : dark ? "#ffffff24" : "#171b1818"}`,
      color: accent ? ink : dark ? soft : "#64705f",
      fontSize: 18,
      fontWeight: 550,
      letterSpacing: 0.3,
    }}
  >
    {children}
  </span>
);

const Chapter = ({
  n,
  name,
  dark = false,
  orangePage = false,
  children,
  illustrative = true,
}: {
  n: string;
  name: string;
  dark?: boolean;
  orangePage?: boolean;
  children: ReactNode;
  illustrative?: boolean;
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: orangePage ? orange : dark ? ink : paper,
        color: dark ? paper : ink,
        overflow: "hidden",
      }}
    >
      <AbsoluteFill
        style={{
          opacity: dark ? 0.24 : 0.42,
          backgroundImage: `radial-gradient(${dark ? "#abbda32d" : "#1a241417"} 0.8px, transparent 0.8px)`,
          backgroundSize: "12px 12px",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 940,
          height: 940,
          border: `1px solid ${dark ? "#ffffff09" : "#171b1809"}`,
          borderRadius: "50%",
          left: 1020 + Math.sin(frame * 0.009) * 10,
          top: -320,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 52,
          left: 96,
          right: 96,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Mark size={58} dark={orangePage} />
          <span style={{ fontSize: 33, letterSpacing: -1.4, fontWeight: 630 }}>
            chatty
          </span>
        </div>
        <span style={{ ...label, opacity: 0.58, fontSize: 16 }}>
          Your AI meeting teammate
        </span>
      </div>
      {children}
      <div
        style={{
          position: "absolute",
          bottom: 157,
          left: 96,
          right: 96,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          opacity: 0.72,
        }}
      >
        <span style={{ ...label, fontSize: 15 }}>
          {n} <span style={{ marginLeft: 21 }}>{name}</span>
        </span>
        {illustrative && (
          <span style={{ fontSize: 16, letterSpacing: 0.4 }}>
            Illustrative workflow · Fictional example
          </span>
        )}
      </div>
    </AbsoluteFill>
  );
};

const Bubble = ({
  text,
  who,
  tone = "dark",
  style,
}: {
  text: string;
  who: string;
  tone?: "dark" | "light" | "orange";
  style?: CSSProperties;
}) => (
  <div
    style={{
      padding: "25px 32px 29px",
      borderRadius: "24px 24px 24px 6px",
      background:
        tone === "orange" ? orange : tone === "dark" ? ink : "#fffdf6",
      color: tone === "dark" ? paper : ink,
      boxShadow: "0 18px 55px #0b150b0c",
      ...style,
    }}
  >
    <div style={{ ...label, fontSize: 14, opacity: 0.56, marginBottom: 12 }}>
      {who}
    </div>
    <div
      style={{
        fontSize: 33,
        lineHeight: 1.26,
        fontWeight: 470,
        letterSpacing: -1,
      }}
    >
      {text}
    </div>
  </div>
);

const Problem = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="01" name="The familiar moment" illustrative={false}>
      <Reveal style={{ position: "absolute", top: 242, left: 96 }}>
        <div style={{ ...label, color: "#687162", marginBottom: 30 }}>
          One meeting. Too many tabs.
        </div>
        <h1 style={{ ...headline, fontSize: 125, lineHeight: 1.02 }}>
          Your team
          <br />
          is talking.
        </h1>
        <div
          style={{
            color: "#687162",
            fontSize: 35,
            marginTop: 33,
            letterSpacing: -1,
          }}
        >
          The answers are somewhere else.
        </div>
      </Reveal>
      <div style={{ position: "absolute", width: 660, top: 210, right: 102 }}>
        <Reveal
          delay={11}
          style={{
            transform: `rotate(-3deg) translateY(${(1 - enter(frame, 11)) * 30}px)`,
            opacity: enter(frame, 11),
          }}
        >
          <Bubble
            who="In the meeting"
            text="“What caused the login bug?”"
            tone="dark"
            style={{ paddingBottom: 10 }}
          />
          <div
            style={{
              background: ink,
              padding: "0 34px 22px",
              borderRadius: "0 0 24px 24px",
              marginTop: -22,
            }}
          >
            <Wave width={590} />
          </div>
        </Reveal>
        <Reveal
          delay={31}
          style={{
            margin: "25px -12px 0 82px",
            transform: `rotate(3deg) translateY(${(1 - enter(frame, 31)) * 30}px)`,
            opacity: enter(frame, 31),
          }}
        >
          <Bubble
            who="Another teammate"
            text="“Who’s picking it up?”"
            tone="orange"
          />
        </Reveal>
        <Reveal
          delay={65}
          style={{
            display: "flex",
            gap: 12,
            justifyContent: "flex-end",
            marginTop: 42,
          }}
        >
          <Pill>Knowledge</Pill>
          <Pill>Tickets</Pill>
          <Pill>Work systems</Pill>
        </Reveal>
      </div>
    </Chapter>
  );
};

const Introduction = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="02" name="Bring Chatty in" dark>
      <Reveal style={{ position: "absolute", left: 96, top: 259 }}>
        <div style={{ ...label, color: orange, marginBottom: 31 }}>
          A seat in the conversation
        </div>
        <h1 style={headline}>
          Meet your
          <br />
          next <span style={{ color: orange }}>teammate.</span>
        </h1>
        <p
          style={{
            fontSize: 31,
            lineHeight: 1.42,
            color: soft,
            width: 630,
            marginTop: 37,
          }}
        >
          Your context and useful actions.
          <br />
          Right inside the meeting.
        </p>
      </Reveal>
      <div
        style={{
          position: "absolute",
          left: 1020,
          top: 180,
          width: 800,
          height: 584,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
        }}
      >
        {[
          { name: "Alex", letter: "A", color: "#b7c4ad" },
          { name: "Maya", letter: "M", color: "#d8b29b" },
          { name: "Sam", letter: "S", color: "#a9bac7" },
        ].map((p, i) => (
          <Reveal
            key={p.name}
            delay={8 + i * 6}
            style={{
              height: 275,
              borderRadius: 23,
              background: "#232a24",
              padding: 24,
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              position: "relative",
            }}
          >
            <div
              style={{
                width: 110,
                height: 110,
                borderRadius: "50%",
                color: ink,
                background: p.color,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 48,
                fontWeight: 550,
              }}
            >
              {p.letter}
            </div>
            <span
              style={{
                position: "absolute",
                left: 24,
                bottom: 20,
                fontSize: 21,
                color: soft,
              }}
            >
              {p.name}
            </span>
          </Reveal>
        ))}
        <Reveal
          delay={30}
          style={{
            height: 275,
            borderRadius: 23,
            background: paper,
            color: ink,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            position: "relative",
            boxShadow: `0 0 ${28 + 10 * Math.sin(frame * 0.05)}px #ff71462b`,
          }}
        >
          <Mark size={206} />
          <span
            style={{
              position: "absolute",
              left: 24,
              bottom: 20,
              fontSize: 21,
              fontWeight: 580,
            }}
          >
            Chatty <span style={{ opacity: 0.6, fontSize: 16 }}>· AI</span>
          </span>
          <div
            style={{
              position: "absolute",
              right: 25,
              bottom: 24,
              display: "flex",
              gap: 4,
            }}
          >
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{
                  height: 14 + 10 * Math.abs(Math.sin(frame * 0.1 - i)),
                  width: 4,
                  background: ink,
                  borderRadius: 5,
                }}
              />
            ))}
          </div>
        </Reveal>
      </div>
      <Reveal delay={74} style={{ position: "absolute", left: 1020, top: 792 }}>
        <Pill dark>“Chatty, what changed?”</Pill>
      </Reveal>
    </Chapter>
  );
};

const Context = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="03" name="Connect the work" dark>
      <Reveal style={{ position: "absolute", top: 212, left: 96 }}>
        <div style={{ ...label, color: orange, marginBottom: 32 }}>
          Built for connected work
        </div>
        <h1 style={{ ...headline, fontSize: 105 }}>
          Your tools.
          <br />
          Your data.
          <br />
          <span style={{ color: orange }}>One conversation.</span>
        </h1>
        <div
          style={{ marginTop: 35, color: soft, fontSize: 28, lineHeight: 1.42 }}
        >
          With a supported connection
          <br />
          and your permission.
        </div>
        <div style={{ marginTop: 23 }}>
          <Wave width={530} />
        </div>
      </Reveal>
      <div style={{ position: "absolute", left: 1050, top: 184, width: 772 }}>
        <Reveal delay={8}>
          <div
            style={{ ...label, fontSize: 16, color: soft, marginBottom: 25 }}
          >
            How Chatty helps
          </div>
        </Reveal>
        {[
          {
            type: "READ",
            title: "Find the relevant context",
            desc: "Bring the information you authorize into the room.",
            icon: "↗",
          },
          {
            type: "UNDERSTAND",
            title: "Answer in the conversation",
            desc: "Questions, follow-ups and useful source references.",
            icon: "◇",
          },
          {
            type: "ACT",
            title: "Move tickets and tasks forward",
            desc: "Review the draft. Approve the action. Verify the result.",
            icon: "→",
          },
        ].map((item, i) => (
          <Reveal
            key={item.type}
            delay={18 + i * 24}
            style={{
              padding: "24px 30px",
              background: i === 0 ? "#2a342a" : "#212822",
              border: "1px solid #ffffff15",
              borderRadius: 20,
              marginBottom: 15,
              transform: `translateX(${(1 - enter(frame, 18 + i * 24)) * 65}px)`,
              opacity: enter(frame, 18 + i * 24),
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 13,
              }}
            >
              <span style={{ ...label, fontSize: 14, color: orange }}>
                {item.type}
              </span>
              <span style={{ color: orange, fontSize: 24, lineHeight: 0.8 }}>
                {item.icon}
              </span>
            </div>
            <div style={{ fontSize: 31, letterSpacing: -0.8 }}>
              {item.title}
            </div>
            <div style={{ fontSize: 20, color: soft, marginTop: 9 }}>
              {item.desc}
            </div>
          </Reveal>
        ))}
        <Reveal
          delay={95}
          style={{
            padding: "20px 23px",
            border: "1px solid #b5d6a54a",
            borderRadius: 14,
            color: green,
            fontSize: 23,
            lineHeight: 1.45,
            marginTop: 21,
          }}
        >
          <strong style={{ fontWeight: 590 }}>Current demo: GitHub</strong>
          <br />
          <span style={{ color: soft }}>More connectors planned</span>
        </Reveal>
      </div>
    </Chapter>
  );
};

const Followup = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="04" name="Stay in the flow">
      <Reveal style={{ position: "absolute", left: 96, top: 263 }}>
        <div style={{ ...label, color: "#687162", marginBottom: 31 }}>
          Built for the conversation
        </div>
        <h1 style={headline}>
          Say her
          <br />
          name once.
          <br />
          <span style={{ color: "#d85c36" }}>Keep talking.</span>
        </h1>
        <p style={{ fontSize: 30, color: "#687162", marginTop: 35 }}>
          Follow up. Ask. Refine.
        </p>
      </Reveal>
      <div style={{ position: "absolute", left: 1050, top: 180, width: 766 }}>
        <Reveal delay={7}>
          <Bubble
            who="Alex"
            text="“Chatty, turn what we agreed into a ticket.”"
          />
        </Reveal>
        <Reveal delay={63} style={{ margin: "19px 0 0 66px" }}>
          <Bubble
            who="Alex · Follow-up"
            text="“What’s the title?”"
            tone="orange"
          />
        </Reveal>
        <Reveal delay={117} style={{ margin: "19px 48px 0 0" }}>
          <Bubble
            who="Chatty · Draft details"
            text="“The draft title is: Fix login retry handling.”"
            tone="light"
          />
        </Reveal>
      </div>
      <div
        style={{
          position: "absolute",
          width: 7,
          height: 320 * enter(frame, 22, 140),
          borderRadius: 9,
          background: "#d4d8ca",
          left: 1007,
          top: 245,
        }}
      />
    </Chapter>
  );
};

const Revision = () => {
  const frame = useCurrentFrame();
  const revised = frame >= 55;
  return (
    <Chapter n="05" name="Shape the decision" orangePage>
      <Reveal style={{ position: "absolute", left: 96, top: 240 }}>
        <div style={{ ...label, opacity: 0.64, marginBottom: 30 }}>
          You stay in control
        </div>
        <h1 style={{ ...headline, fontSize: 104 }}>
          Decisions change.
          <br />
          The draft
          <br />
          can too.
        </h1>
        <div style={{ fontSize: 31, marginTop: 43, opacity: 0.75 }}>
          A short summary.
          <br />A clear go-ahead.
        </div>
      </Reveal>
      <div style={{ position: "absolute", left: 1050, top: 167, width: 766 }}>
        <Reveal delay={7}>
          <Bubble
            who="Alex"
            text="“Actually, call it Fix login timeout.”"
            tone="dark"
          />
        </Reveal>
        <Reveal
          delay={28}
          style={{
            marginTop: 19,
            background: paper,
            border: "1px solid #171b1815",
            borderRadius: 21,
            padding: "23px 30px",
          }}
        >
          <div style={{ ...label, fontSize: 14, opacity: 0.56 }}>
            Ticket draft
          </div>
          <div
            style={{
              fontSize: revised ? 22 : 31,
              marginTop: 10,
              letterSpacing: -0.8,
              textDecoration: revised ? "line-through" : "none",
              opacity: revised ? 0.4 : 1,
            }}
          >
            Fix login retry handling
          </div>
          {revised && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                fontSize: 32,
                marginTop: 14,
                opacity: enter(frame, 55),
                color: "#426437",
                letterSpacing: -0.8,
              }}
            >
              <Check size={25} /> Fix login timeout
            </div>
          )}
        </Reveal>
        <Reveal delay={104} style={{ marginTop: 19 }}>
          <Bubble
            who="Chatty"
            text="“I’ll create the login timeout ticket with the fix we discussed. Do you approve?”"
            tone="light"
          />
        </Reveal>
      </div>
    </Chapter>
  );
};

const Approval = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="06" name="Turn agreement into action" dark>
      <Reveal style={{ position: "absolute", left: 96, top: 236 }}>
        <div style={{ ...label, color: orange, marginBottom: 33 }}>
          Real tools. Human permission.
        </div>
        <h1 style={{ ...headline, fontSize: 118 }}>
          Your voice.
          <br />
          <span style={{ color: orange }}>Your go-ahead.</span>
        </h1>
        <p
          style={{ fontSize: 32, color: soft, lineHeight: 1.45, marginTop: 37 }}
        >
          From a meeting decision
          <br />
          to work in your connected tools.
        </p>
      </Reveal>
      <div style={{ position: "absolute", left: 1050, top: 187, width: 766 }}>
        <Reveal delay={9}>
          <Bubble who="Alex" text="“Sure, go ahead.”" tone="orange" />
        </Reveal>
        <Reveal
          delay={66}
          style={{
            marginTop: 34,
            background: "#242d25",
            border: "1px solid #b5d6a52d",
            padding: "34px 34px 30px",
            borderRadius: 25,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 26,
            }}
          >
            <Pill accent>
              <Check size={21} /> Issue created
            </Pill>
            <span style={{ color: soft, fontSize: 15 }}>
              GitHub example · Illustrative result
            </span>
          </div>
          <div style={{ fontSize: 39, lineHeight: 1.14, letterSpacing: -1.3 }}>
            Fix login timeout
          </div>
          <div style={{ marginTop: 22, fontSize: 23, color: soft }}>
            Includes the agreed fix
          </div>
          <div
            style={{
              height: 1,
              background: "#ffffff14",
              marginTop: 31,
              marginBottom: 24,
            }}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ color: green, fontSize: 23 }}>View issue</span>
            <span style={{ color: green, fontSize: 30 }}>↗</span>
          </div>
        </Reveal>
        <Reveal delay={110}>
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
              color: soft,
              fontSize: 19,
              marginTop: 22,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: green,
                opacity: 0.6 + Math.sin(frame / 16) * 0.15,
              }}
            />{" "}
            A result you can verify
          </div>
        </Reveal>
      </div>
    </Chapter>
  );
};

const Quiet = () => {
  const frame = useCurrentFrame();
  const quiet = frame >= 100;
  return (
    <Chapter n="07" name="Stay in control">
      <Reveal style={{ position: "absolute", left: 96, top: 248 }}>
        <div style={{ ...label, color: "#687162", marginBottom: 33 }}>
          There when you need her
        </div>
        <h1 style={{ ...headline, fontSize: 112 }}>
          Helpful.
          <br />
          Until you
          <br />
          <span style={{ color: "#d85c36" }}>say stop.</span>
        </h1>
      </Reveal>
      <div style={{ position: "absolute", left: 1070, top: 213, width: 730 }}>
        <Reveal delay={7}>
          <Bubble who="Alex" text="“Chatty, stop.”" tone="dark" />
        </Reveal>
        <Reveal delay={67} style={{ margin: "22px 0 0 300px" }}>
          <Bubble who="Chatty" text="“Okay.”" tone="orange" />
        </Reveal>
        <Reveal
          delay={100}
          style={{
            marginTop: 38,
            background: "#e5e8dd",
            borderRadius: 24,
            padding: "23px 35px 28px",
          }}
        >
          <Wave color="#708665" quiet={quiet} width={660} />
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: 12,
              fontSize: 22,
              color: "#56684d",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                background: "#829875",
                borderRadius: "50%",
              }}
            />{" "}
            Listening quietly
          </div>
        </Reveal>
      </div>
    </Chapter>
  );
};

const Finale = () => {
  const frame = useCurrentFrame();
  return (
    <Chapter n="08" name="Keep the conversation moving" illustrative={false}>
      <div style={{ position: "absolute", left: 96, top: 183, width: 1110 }}>
        <Reveal>
          <div style={{ fontSize: 100, fontWeight: 650, letterSpacing: -6.5 }}>
            chatty
          </div>
        </Reveal>
        <Reveal delay={16}>
          <h1
            style={{
              ...headline,
              fontSize: 117,
              lineHeight: 1.035,
              marginTop: 31,
            }}
          >
            From conversation
            <br />
            to <span style={{ color: "#d85c36" }}>action.</span>
          </h1>
        </Reveal>
        <Reveal delay={29}>
          <div
            style={{
              color: "#687162",
              fontSize: 31,
              marginTop: 29,
              letterSpacing: -0.8,
            }}
          >
            Your tools. Your data. One conversation.
          </div>
        </Reveal>
        <Reveal delay={42}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 25,
              marginTop: 42,
            }}
          >
            <div
              style={{
                background: ink,
                color: paper,
                padding: "18px 25px",
                fontSize: 23,
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                gap: 30,
              }}
            >
              Explore Chatty <span>↗</span>
            </div>
            <span style={{ fontSize: 24, letterSpacing: -0.6 }}>
              github.com/vaishnavJa/Chatty
            </span>
          </div>
        </Reveal>
      </div>
      <Reveal
        delay={22}
        style={{
          position: "absolute",
          right: 79,
          top: 214,
          width: 530,
          height: 530,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 17,
            background: "#e9e7dc",
            borderRadius: "50%",
          }}
        />
        {[0, 1].map((i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              inset: -12 + i * 34,
              border: "1px solid #171b1810",
              borderRadius: "50%",
              transform: `scale(${1 + Math.sin(frame * 0.025 - i) * 0.02})`,
            }}
          />
        ))}
        <div
          style={{
            position: "relative",
            transform: `translateY(${Math.sin(frame * 0.035) * 7}px) rotate(${Math.sin(frame * 0.022) * 1.4}deg)`,
          }}
        >
          <Mark size={530} />
        </div>
      </Reveal>
      <div
        style={{
          position: "absolute",
          right: 96,
          bottom: 157,
          fontSize: 16,
          opacity: 0.69,
        }}
      >
        Synthetic narration · Illustrative product animation
      </div>
    </Chapter>
  );
};

const scenes = [
  Problem,
  Introduction,
  Context,
  Followup,
  Revision,
  Approval,
  Quiet,
  Finale,
];

// The short paragraphs stay visible over their measured speech intervals.
// These match the SRT rather than switching sentences at arbitrary scene cuts.
const Caption = ({
  text,
  start,
  end,
}: {
  text: string;
  start: number;
  end: number;
}) => {
  const frame = useCurrentFrame();
  if (frame < start * 30 || frame > end * 30) return null;
  return (
    <div
      style={{
        position: "absolute",
        bottom: 47,
        left: 160,
        right: 160,
        display: "flex",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      <div
        style={{
          background: "#101612ee",
          color: paper,
          padding: "15px 28px 17px",
          borderRadius: 10,
          fontSize: 26,
          lineHeight: 1.34,
          letterSpacing: -0.3,
          maxWidth: 1540,
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const ChattyAd60 = ({
  sound = true,
  captions = true,
}: {
  sound?: boolean;
  captions?: boolean;
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{ fontFamily: "Geist, sans-serif", background: paper }}
    >
      {script.map((part, i) => {
        const Scene = scenes[i];
        return (
          <Sequence
            key={part.id}
            from={part.start * 30}
            durationInFrames={part.duration * 30}
          >
            <Scene />
            {captions && (
              <Caption
                text={part.text}
                start={timings[i].spokenStart - part.start}
                end={timings[i].spokenEnd - part.start}
              />
            )}
          </Sequence>
        );
      })}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          height: 4,
          background: ink,
          opacity: 0.65,
          width: `${(frame / (AD_FRAMES - 1)) * 100}%`,
        }}
      />
      {sound && <Audio src={staticFile("audio/ad/chatty-ad-mix.wav")} />}
    </AbsoluteFill>
  );
};
