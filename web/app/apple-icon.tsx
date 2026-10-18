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
        }}
      >
        <svg width={130} height={116} viewBox="14 20 72 64">
          <circle cx="44" cy="52" r="26" fill="#ffffff" />
          <circle cx="62" cy="52" r="17" fill="#0e5a55" />
          <circle cx="62" cy="52" r="13" fill="#e39b35" />
        </svg>
      </div>
    ),
    size,
  );
}
