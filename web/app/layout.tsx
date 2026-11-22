import type { Metadata, Viewport } from "next";
import { Archivo, Permanent_Marker } from "next/font/google";
import "./globals.css";

// Workhorse grotesque with a width axis: condensed for figures and names, normal for UI.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin", "latin-ext"],
  axes: ["wdth"],
  display: "swap",
});

// Marker lettering annotates the board; it never carries data people must read.
const marker = Permanent_Marker({
  variable: "--font-marker",
  weight: "400",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "FPL Agent: your gameweek, planned",
  description:
    "Enter your Fantasy Premier League team ID and get this week's transfers, captain and chip plan, with the stats behind every pick and how it plays against your mini-league.",
};

export const viewport: Viewport = {
  themeColor: "#E6E8EB",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-GB">
      <body className={`${archivo.variable} ${marker.variable}`}>{children}</body>
    </html>
  );
}
