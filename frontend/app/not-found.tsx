import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { CanonLine, Wordmark } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";
import { CANON } from "@/lib/canon";
import reichenbach from "@/public/paget/reichenbach.webp";

export const metadata: Metadata = { title: "The Final Problem" };

/** 404: the page went over the Reichenbach Falls. */
export default function NotFound() {
  return (
    <main
      id="main"
      className="grain mx-auto grid min-h-[100dvh] w-full max-w-[1240px] items-center gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1fr_0.8fr]"
    >
      <div className="max-w-xl">
        <Link
          href="/"
          className="focus-visible:ring-ring/60 inline-block rounded-lg outline-none focus-visible:ring-3"
        >
          <Wordmark />
        </Link>
        <p className="text-brand-ink mt-16 font-mono text-sm">404</p>
        <h1 className="mt-3 text-5xl leading-[0.98] font-semibold tracking-[-0.045em] md:text-6xl">
          This page went over the Reichenbach Falls.
        </h1>
        <p className="text-muted-foreground mt-5 max-w-[46ch] text-lg leading-relaxed">
          Like Holmes in 1893, it may yet turn up. Until then, nothing at this
          address.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/review" className={buttonVariants({ size: "lg" })}>
            Back to your review queue
          </Link>
          <Link
            href="/"
            className={buttonVariants({ size: "lg", variant: "ghost" })}
          >
            Home
          </Link>
        </div>
        <CanonLine {...CANON.impossible} className="mt-14" />
      </div>
      <div className="mx-auto w-full max-w-[420px] [mask-image:radial-gradient(ellipse_58%_56%_at_50%_42%,black_35%,transparent_100%)]">
        <Image
          src={reichenbach}
          alt="Sidney Paget's 1893 illustration of Holmes and Moriarty grappling at the edge of the Reichenbach Falls."
          sizes="(min-width: 768px) 420px, 90vw"
          placeholder="blur"
          className="paget h-auto w-full"
        />
      </div>
    </main>
  );
}
