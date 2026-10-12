"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { Wordmark } from "@/components/brand";
import { useMe } from "@/lib/auth";

const LINKS = [
  { href: "#method", label: "How it works" },
  { href: "#open-outreach", label: "Open outreach" },
  { href: "#rules", label: "Safety" },
];

/** The primary action, one label per intent: "Sign in" when signed out, "Open Sherlock" when not. */
export function PrimaryAction({
  size = "default",
}: {
  size?: "default" | "lg";
}) {
  const me = useMe();
  const signedIn = me.isSuccess;
  const big = size === "lg";
  return (
    <Link
      href={signedIn ? "/review" : "/login"}
      className={`group bg-brand text-brand-foreground shadow-soft focus-visible:ring-ring/60 inline-flex items-center gap-2 rounded-full font-medium whitespace-nowrap transition-[transform,background-color] duration-300 ease-(--ease-spring) outline-none hover:bg-[color-mix(in_oklch,var(--brand),var(--foreground)_8%)] focus-visible:ring-3 active:scale-[0.97] ${big ? "h-12 pr-1.5 pl-6 text-base" : "h-9 pr-1 pl-4 text-sm"}`}
    >
      {signedIn ? "Open Sherlock" : "Sign in"}
      <span
        className={`bg-brand-foreground/10 flex items-center justify-center rounded-full transition-transform duration-300 ease-(--ease-spring) group-hover:translate-x-0.5 group-hover:-translate-y-px ${big ? "size-9" : "size-7"}`}
      >
        <ArrowUpRight className={big ? "size-4" : "size-3.5"} />
      </span>
    </Link>
  );
}

export function LandingNav() {
  return (
    <header className="fixed inset-x-0 top-4 z-40 flex justify-center px-4">
      <nav
        aria-label="Primary"
        className="bg-background/70 ring-foreground/[0.08] shadow-soft edge-highlight flex h-14 w-full max-w-3xl items-center justify-between gap-4 rounded-full pr-2 pl-5 ring-1 backdrop-blur-xl"
      >
        <Link
          href="/"
          className="focus-visible:ring-ring/60 rounded-lg outline-none focus-visible:ring-3"
        >
          <Wordmark />
        </Link>
        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/60 rounded-full px-3 py-1.5 text-sm transition-colors duration-200 outline-none focus-visible:ring-3"
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>
        <PrimaryAction />
      </nav>
    </header>
  );
}
