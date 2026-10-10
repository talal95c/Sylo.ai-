import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sylo.ai — the cheapest compliant route, and a window to stop the money",
  description: "Decision and control layer for cross-border business payments. Demo on synthetic data: every rail and chain transaction is simulated.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full">{children}</body>
    </html>
  );
}
