import { ImageResponse } from "next/og";

// App icons for the manifest and the browser tab: the logo mark (docs/design/DESIGN.md, Marca) in white on
// brand green, with the amber dot. "maskable" keeps the mark inside the 80% safe zone so Android can crop it.
const SIZES = { "192": 192, "512": 512, maskable: 512 } as const;
type IconId = keyof typeof SIZES;

const GREEN = "#0e5a55";
const AMBER = "#e39b35";

export function generateImageMetadata() {
  return (Object.keys(SIZES) as IconId[]).map((id) => ({
    id,
    contentType: "image/png",
    size: { width: SIZES[id], height: SIZES[id] },
  }));
}

function Mark({ size }: { size: number }) {
  return (
    <svg width={size} height={(size * 64) / 72} viewBox="14 20 72 64">
      <circle cx="44" cy="52" r="26" fill="#ffffff" />
      <circle cx="62" cy="52" r="17" fill={GREEN} />
      <circle cx="62" cy="52" r="13" fill={AMBER} />
    </svg>
  );
}

export default async function Icon({ id }: { id: Promise<string> }) {
  const iconId = (await id) as IconId;
  const size = SIZES[iconId] ?? 512;
  const scale = iconId === "maskable" ? 0.56 : 0.74;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: GREEN,
        }}
      >
        <Mark size={Math.round(size * scale)} />
      </div>
    ),
    { width: size, height: size },
  );
}
