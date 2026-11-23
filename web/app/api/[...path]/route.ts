import type { NextRequest } from "next/server";
import { apiBase } from "@/lib/api";

// The browser stays on this origin; this route forwards /api/* to the Python
// planning API. Reading FPL_API_URL at request time (not build time) means the
// deployed URL lives in one place: the Worker's vars (wrangler.jsonc), or the
// shell locally. Only GET is forwarded, so /api/refresh stays scheduler-only.
export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = `${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(target, { headers: { accept: "application/json" }, signal: req.signal, cache: "no-store" });
  } catch {
    return Response.json({ detail: "Can't reach the planner right now. Try again in a minute." }, { status: 502 });
  }
  const headers = new Headers({ "content-type": upstream.headers.get("content-type") ?? "application/json" });
  const retry = upstream.headers.get("retry-after");
  if (retry) headers.set("retry-after", retry);
  return new Response(upstream.body, { status: upstream.status, headers });
}
