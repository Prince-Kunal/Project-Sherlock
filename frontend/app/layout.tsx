import type { Metadata, Viewport } from "next";
import { EB_Garamond, Geist, Geist_Mono } from "next/font/google";

import { THEME_SCRIPT } from "@/lib/theme";

import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Only for quotations from the Holmes stories.
const garamond = EB_Garamond({
  variable: "--font-serif",
  subsets: ["latin"],
  style: ["italic"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  ),
  title: {
    default: "Sherlock: referrals, deduced",
    template: "%s · Sherlock",
  },
  description:
    "Sherlock finds fresh openings, the person who can refer you, and drafts the email. You approve every word.",
  openGraph: {
    title: "Sherlock: referrals, deduced",
    description:
      "Fresh openings, the right person to ask, and a short email you approve before it goes.",
    images: ["/paget/carriage.webp"],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
    { media: "(prefers-color-scheme: dark)", color: "#14171c" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${garamond.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="bg-brand text-brand-foreground sr-only z-[70] rounded-full px-4 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
