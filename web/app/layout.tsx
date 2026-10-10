import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sylo.ai · cross-border payment control (simulated demo)",
  description:
    "Sylo.ai checks which routes are legal, scores fraud, picks the cheapest safe route, seals the payment on Avalanche and stops a diverted payment before the money is lost.",
};

export const viewport: Viewport = {
  themeColor: "#060a13",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
