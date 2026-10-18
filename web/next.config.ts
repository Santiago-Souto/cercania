import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

// Backend base URL. Server components call it directly (lib/api.ts); the browser goes through /api.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

// Without it there is no /api rewrite and every browser call 404s with no hint why. `next build` stops;
// anything else (dev, typegen, start) only warns.
function checkApiUrl(phase: string) {
  if (API_URL) return;
  const message = "NEXT_PUBLIC_API_URL is not set: the /api proxy to the backend is disabled.";
  // `next typegen` loads this file in the build phase too, and only needs the routes.
  if (phase === PHASE_PRODUCTION_BUILD && !process.argv.includes("typegen")) throw new Error(message);
  console.warn(`\n⚠  ${message}\n`);
}

const nextConfig: NextConfig = {
  // Lets a second person log in on http://127.0.0.1:3000 (cookies are per host) next to localhost.
  allowedDevOrigins: ["127.0.0.1"],
  cacheComponents: true,
  partialPrefetching: true,
  // The /api rewrite cuts a proxied request off at 30 s by default. A report (transcription + triage +
  // extraction, a Groq 429 retry, or a Render cold start) can take longer and would show an error for a
  // report that was actually saved.
  experimental: { proxyTimeout: 120_000 },
  // Same-origin proxy for browser calls: the session cookie from POST /auth/verify becomes first-party on
  // the web origin. Web and API are different sites on Render, where a cross-site cookie gets blocked.
  async rewrites() {
    return API_URL ? [{ source: "/api/:path*", destination: `${API_URL}/:path*` }] : [];
  },
};

export default function config(phase: string): NextConfig {
  checkApiUrl(phase);
  return nextConfig;
}
