import { ImageResponse } from "next/og";
import { BACKGROUND, Mark } from "@/lib/app-icon";

// Home-screen icon for iPhone/iPad (iOS ignores the manifest icons). iOS rounds the corners itself.
// See lib/app-icon.tsx for why the background is a gradient (iOS dark mode).
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
          backgroundImage: BACKGROUND,
        }}
      >
        <Mark size={130} />
      </div>
    ),
    size,
  );
}
