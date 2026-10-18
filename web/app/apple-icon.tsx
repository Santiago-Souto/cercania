import { ImageResponse } from "next/og";

// Home-screen icon for iPhone/iPad (iOS ignores the manifest icons). iOS rounds the corners itself.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0e5a55",
          color: "#ffffff",
          fontSize: 118,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        C
      </div>
    ),
    size,
  );
}
