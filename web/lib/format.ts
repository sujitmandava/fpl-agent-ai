export const signed = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;

export const signedInt = (v: number) => (v > 0 ? `+${v}` : v < 0 ? `−${Math.abs(v)}` : "0");

export const fixed = (v: number | null | undefined, digits = 1) => (v == null ? "—" : v.toFixed(digits));

export const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export const money = (v: number | null | undefined) => (v == null ? "—" : `£${v.toFixed(1)}m`);

export const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};

/** "Fri 27 Nov, 18:30" in the visitor's own time zone. */
export function deadline(iso: string | null): string {
  if (!iso) return "deadline unknown";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Counter label: web names are short already; cap the rare long one. */
export const counterName = (name: string) => (name.length > 11 ? `${name.slice(0, 10)}…` : name);

/** First name of a manager, for "Rohan owns him". */
export const firstName = (full: string) => full.split(/\s+/)[0] || full;
