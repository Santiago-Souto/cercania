import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets the demo run a second persona on http://127.0.0.1:3000 (cookies are per host) next to localhost.
  allowedDevOrigins: ["127.0.0.1"],
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
