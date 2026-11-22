"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useMemo, useState } from "react";
import { ClipboardList, Trophy, Users, Search, MoreHorizontal, ArrowLeftRight } from "lucide-react";
import styles from "./Shell.module.css";

const SECTIONS = [
  { slug: "", label: "Plan", icon: ClipboardList },
  { slug: "league", label: "League", icon: Trophy },
  { slug: "squad", label: "Squad", icon: Users },
  { slug: "players", label: "Players", icon: Search },
  { slug: "more", label: "More", icon: MoreHorizontal },
] as const;

// Lets a page tell the shell the team doesn't exist, so it stops offering
// section tabs that would lead nowhere.
const TeamStatus = createContext<{ missing: boolean; setMissing: (v: boolean) => void }>({
  missing: false,
  setMissing: () => {},
});
export const useTeamStatus = () => useContext(TeamStatus);

export default function Shell({ teamId, children }: { teamId: number; children: React.ReactNode }) {
  const pathname = usePathname();
  const [missing, setMissing] = useState(false);
  const status = useMemo(() => ({ missing, setMissing }), [missing]);
  const base = `/team/${teamId}`;

  const items = SECTIONS.map((s) => {
    const href = s.slug ? `${base}/${s.slug}` : base;
    const active = s.slug ? pathname.startsWith(href) : pathname === base;
    return { ...s, href, active };
  });

  return (
    <TeamStatus.Provider value={status}>
    <div className={`${styles.shell} ${missing ? styles.bare : ""}`}>
      <nav className={styles.rail} aria-label="Sections">
        <Link href="/" className={styles.brand}>FPL Agent</Link>
        {!missing && <ul>
          {items.map(({ href, label, icon: Icon, active }) => (
            <li key={href}>
              <Link href={href} className={styles.railItem} aria-current={active ? "page" : undefined}>
                <Icon size={18} strokeWidth={2} aria-hidden />
                {label}
              </Link>
            </li>
          ))}
        </ul>}
        <Link href="/" className={styles.switch}>
          <ArrowLeftRight size={16} aria-hidden /> Switch team
        </Link>
      </nav>

      <main className={styles.main}>{children}</main>

      {!missing && <nav className={styles.tabbar} aria-label="Sections">
        {items.map(({ href, label, icon: Icon, active }) => (
          <Link key={href} href={href} className={styles.tab} aria-current={active ? "page" : undefined}>
            <Icon size={20} strokeWidth={active ? 2.4 : 1.9} aria-hidden />
            <span>{label}</span>
          </Link>
        ))}
      </nav>}
    </div>
    </TeamStatus.Provider>
  );
}
