import type { NextConfig } from "next";

// Backend base URL. Server components call it directly (lib/api.ts); the browser goes through /api.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Lets a second person log in on http://127.0.0.1:3000 (cookies are per host) next to localhost.
  allowedDevOrigins: ["127.0.0.1"],
  cacheComponents: true,
  partialPrefetching: true,
  // Same-origin proxy for browser calls: the session cookie from POST /auth/verify becomes first-party on
  // the web origin. Web and API are different sites on Render, where a cross-site cookie gets blocked.
  async rewrites() {
    return API_URL ? [{ source: "/api/:path*", destination: `${API_URL}/:path*` }] : [];
  },
};

export default nextConfig;
