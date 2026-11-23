import type { NextConfig } from "next";
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

// /api/* is forwarded to the Python engine by app/api/[...path]/route.ts, which
// reads FPL_API_URL at request time (default http://127.0.0.1:8000 for
// `python fpl_agent.py api`).
const nextConfig: NextConfig = {
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;

// Lets `next dev` see the Cloudflare bindings in wrangler.jsonc.
initOpenNextCloudflareForDev();
