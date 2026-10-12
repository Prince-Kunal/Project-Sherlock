"use client";

import { motion, useReducedMotion } from "motion/react";

import { LensImage } from "@/components/landing/lens-image";
import { PrimaryAction } from "@/components/landing/landing-nav";
import carriage from "@/public/paget/carriage.webp";

const EASE = [0.16, 1, 0.3, 1] as const;

export function Hero() {
  const reduce = useReducedMotion();
  const enter = (delay: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 24, filter: "blur(8px)" },
          animate: { opacity: 1, y: 0, filter: "blur(0px)" },
          transition: { duration: 1, delay, ease: EASE },
        };

  return (
    <section className="relative overflow-hidden">
      {/* Gaslight in the fog, behind the plate. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-[-10%] right-[-15%] h-[70vh] w-[70vw] rounded-full opacity-60 blur-3xl"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklch, var(--brand) 28%, transparent), transparent)",
        }}
      />
      <div className="mx-auto grid min-h-[100dvh] w-full max-w-[1240px] items-center gap-10 px-4 pt-24 pb-12 sm:px-6 md:grid-cols-[1.05fr_1fr] md:gap-6">
        <div className="relative z-10 max-w-xl">
          <motion.h1
            {...enter(0.05)}
            className="text-[3.6rem] leading-[0.95] font-semibold tracking-[-0.05em] sm:text-7xl lg:text-[5.6rem]"
          >
            Referrals,
            <br />
            <span className="text-brand-ink">deduced.</span>
          </motion.h1>
          <motion.p
            {...enter(0.18)}
            className="text-muted-foreground mt-6 max-w-[38ch] text-lg leading-relaxed"
          >
            Sherlock finds fresh openings, the person who can refer you, and
            drafts a short email. You approve every word.
          </motion.p>
          <motion.div
            {...enter(0.3)}
            className="mt-9 flex flex-wrap items-center gap-3"
          >
            <PrimaryAction size="lg" />
            <a
              href="#method"
              className="text-foreground hover:bg-muted focus-visible:ring-ring/60 ring-foreground/10 inline-flex h-12 items-center rounded-full px-6 text-base font-medium ring-1 transition-colors duration-200 outline-none ring-inset focus-visible:ring-3"
            >
              See how it works
            </a>
          </motion.div>
        </div>

        <motion.div
          initial={reduce ? false : { opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.4, delay: 0.15, ease: EASE }}
          className="relative mx-auto w-full max-w-[620px] [mask-image:radial-gradient(ellipse_70%_66%_at_50%_46%,black_60%,transparent_97%)]"
        >
          <LensImage
            src={carriage}
            priority
            sizes="(min-width: 768px) 46vw, 92vw"
            alt="Sidney Paget's 1892 illustration for Silver Blaze: Holmes, in his deerstalker, sketching the case for Watson in a railway carriage."
          />
        </motion.div>
      </div>
    </section>
  );
}
