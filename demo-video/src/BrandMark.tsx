import { Img, staticFile } from "remotion";

// The supplied PNG is used unchanged. The light backing is layout, not a
// recoloring or edit of the mascot, and keeps it legible on orange scenes.
export const BrandMark = ({
  size = 52,
  dark = false,
}: {
  size?: number;
  dark?: boolean;
}) => (
  <div
    style={{
      width: size,
      height: size,
      flexShrink: 0,
      background: dark ? "#f1f0e8" : "transparent",
      borderRadius: dark ? size * 0.22 : 0,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}
  >
    <Img
      src={staticFile("brand/chatty-mascot.png")}
      alt="Chatty waving mascot"
      style={{
        width: dark ? "91%" : "100%",
        height: dark ? "91%" : "100%",
        objectFit: "contain",
      }}
    />
  </div>
);
