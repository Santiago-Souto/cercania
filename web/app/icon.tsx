import { ImageResponse } from "next/og";

// App icons for the manifest and the browser tab: brand teal (DESIGN.md --primary) with a white "C".
// "maskable" keeps the mark inside the 80% safe zone so Android can crop it to any shape.
const SIZES = { "192": 192, "512": 512, maskable: 512 } as const;
type IconId = keyof typeof SIZES;

export function generateImageMetadata() {
  return (Object.keys(SIZES) as IconId[]).map((id) => ({
    id,
    contentType: "image/png",
    size: { width: SIZES[id], height: SIZES[id] },
  }));
}

export default async function Icon({ id }: { id: Promise<string> }) {
  const iconId = (await id) as IconId;
  const size = SIZES[iconId] ?? 512;
  const scale = iconId === "maskable" ? 0.5 : 0.66;
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
          fontSize: size * scale,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        C
      </div>
    ),
    { width: size, height: size },
  );
}
