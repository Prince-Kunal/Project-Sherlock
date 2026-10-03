import type { NextConfig } from "next";

// Browser calls go to /api/* on the Next server and are proxied to FastAPI, so the session
// cookie is first-party and no CORS is involved.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

export default nextConfig;
