import type { NextConfig } from "next";

// The Python engine serves /api/*. Locally it runs on :8000 (`python fpl_agent.py api`);
// proxying keeps the browser on one origin, the same shape a Vercel deploy will have.
const API_URL = process.env.FPL_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
