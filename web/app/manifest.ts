import type { MetadataRoute } from "next";

// Installable web app ("Agregar a pantalla de inicio"). Online only on purpose: no service worker,
// so every screen always loads live data from the backend.
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "CercanIA",
    short_name: "CercanIA",
    description: "El traspaso de turno que no se pierde.",
    lang: "es",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f5f6f2",
    theme_color: "#0e5a55",
    icons: [
      { src: "/icon/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon/maskable", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
