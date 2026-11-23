import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import kvIncrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/kv-incremental-cache";
import memoryQueue from "@opennextjs/cloudflare/overrides/queue/memory-queue";

// The landing page re-fetches the model check every 6 hours (ISR). KV holds the
// cached page and fits the free plan; the memory queue triggers revalidation
// through the WORKER_SELF_REFERENCE binding.
export default defineCloudflareConfig({
  incrementalCache: kvIncrementalCache,
  queue: memoryQueue,
});
