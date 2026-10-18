// Shared artwork for the app icons (app/icon.tsx, app/apple-icon.tsx). Rendered by next/og (Satori).
//
// iOS dark mode (Home Screen "Automatic"/"Dark" icons) recolors web-clip icons: it detects a flat
// background color and swaps every pixel of it for black. With a flat green background that also
// blackened the green ring around the amber dot. So the background is a gradient (no flat color to
// key out) and the ring is a real cut in the white circle, letting the background show through.

export const AMBER = "#e39b35";
export const BACKGROUND = "linear-gradient(160deg, #13685f 0%, #0e5a55 50%, #0a4c47 100%)";

// White circle (44,52 r26) minus the ring circle (62,52 r17); the arcs meet at x=63.75, y=52±16.91.
const CRESCENT = "M63.75 35.09 A26 26 0 1 0 63.75 68.91 A17 17 0 0 1 63.75 35.09 Z";

export function Mark({ size }: { size: number }) {
  return (
    <svg width={size} height={(size * 64) / 72} viewBox="14 20 72 64">
      <path d={CRESCENT} fill="#ffffff" />
      <circle cx="62" cy="52" r="13" fill={AMBER} />
    </svg>
  );
}
