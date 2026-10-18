import type { NextConfig } from "next";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Lets the demo run a second persona on http://127.0.0.1:3000 (cookies are per host) next to localhost.
  allowedDevOrigins: ["127.0.0.1"],
  cacheComponents: true,
  partialPrefetching: true,
  // Browser calls go to /api/* on the web origin and are proxied to the backend (CIA-32), so the session
  // cookie from POST /auth/verify is first-party and reaches server components too (lib/api-shared.ts).
  async rewrites() {
    return API_URL ? [{ source: "/api/:path*", destination: `${API_URL}/:path*` }] : [];
  },
  experimental: {
    // A free Render API can take ~30-50 s to wake up; the default proxy timeout is 30 s.
    proxyTimeout: 90_000,
  },
};

export default nextConfig;
