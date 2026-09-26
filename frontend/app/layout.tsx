import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted (latin subsets from Google Fonts, OFL licensed) so builds and the
// app itself never depend on fonts.googleapis.com being reachable.
const display = localFont({
  src: [
    { path: "./fonts/ChakraPetch-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ChakraPetch-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ChakraPetch-600.woff2", weight: "600", style: "normal" },
    { path: "./fonts/ChakraPetch-700.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-display",
  display: "swap",
});

const mono = localFont({
  src: "./fonts/JetBrainsMono-latin-variable.woff2",
  weight: "100 800",
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SYRAX",
  description: "SYRAX, son of Ultron. A personal AI operator.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#07080a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="ultron" className={`${display.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
