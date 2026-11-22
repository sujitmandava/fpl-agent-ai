import Link from "next/link";

export default function NotFound() {
  return (
    <main style={{ maxWidth: 560, margin: "0 auto", padding: "64px 16px", display: "grid", gap: 12 }}>
      <h1 style={{ fontSize: 28, fontWeight: 800 }}>Nothing here</h1>
      <p style={{ color: "var(--ink-2)" }}>That page doesn&apos;t exist. Team pages look like /team/1234567.</p>
      <p><Link href="/">Enter your team ID</Link></p>
    </main>
  );
}
