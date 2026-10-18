import { ImageResponse } from "next/og";
import { BACKGROUND, Mark } from "@/lib/app-icon";

// App icons for the manifest and the browser tab: the logo mark (docs/design/DESIGN.md, Marca) in white on
// brand green, with the amber dot (lib/app-icon.tsx). "maskable" keeps the mark inside the 80% safe zone so Android can crop it.
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
          backgroundImage: BACKGROUND,
        }}
      >
        <Mark size={Math.round(size * scale)} />
      </div>
    ),
    { width: size, height: size },
  );
}
