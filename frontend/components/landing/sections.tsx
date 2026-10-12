"use client";

import {
  motion,
  type MotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
} from "motion/react";
import Image from "next/image";
import Link from "next/link";
import { useRef } from "react";
import {
  siGmail,
  siGooglegemini,
  siGreenhouse,
  siYcombinator,
} from "simple-icons";

import { CanonLine, Wordmark } from "@/components/brand";
import { PrimaryAction } from "@/components/landing/landing-nav";
import { Reveal } from "@/components/landing/reveal";
import { CANON } from "@/lib/canon";
import greek from "@/public/paget/greek.webp";
import portrait from "@/public/paget/portrait.webp";

const eyebrow =
  "text-brand-ink text-xs font-semibold tracking-[0.18em] uppercase";

/* --- Works with ---------------------------------------------------------------------------- */

export function Sources() {
  const logos = [siGreenhouse, siYcombinator, siGmail, siGooglegemini];
  return (
    <section aria-label="Works with" className="border-y">
      <div className="mx-auto flex w-full max-w-[1240px] flex-col items-center gap-6 px-4 py-10 sm:px-6 md:flex-row md:justify-between">
        <p className="text-muted-foreground text-sm">
          Reads openings and companies, writes with your Gemini key, sends from
          your Gmail.
        </p>
        <ul className="text-muted-foreground flex flex-wrap items-center gap-x-10 gap-y-4">
          {logos.map((icon) => (
            <li key={icon.slug}>
              <svg
                role="img"
                viewBox="0 0 24 24"
                className="hover:text-foreground size-7 fill-current transition-colors duration-300"
              >
                <title>{icon.title}</title>
                <path d={icon.path} />
              </svg>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* --- The method: pinned narrative ---------------------------------------------------------- */

const STEPS = [
  {
    verb: "Observe",
    body: "Every six hours it reads Greenhouse, Lever, Ashby, Adzuna and Hacker News for openings posted in the last two weeks.",
  },
  {
    verb: "Deduce",
    body: "Each opening is scored against your resume and preferences. Only the ones worth an email reach your queue.",
  },
  {
    verb: "Find",
    body: "It looks for a founder, engineering lead or recruiter at the company, and checks the address before it's used.",
  },
  {
    verb: "Write",
    body: "Your resume is tailored to one page without adding anything you haven't done, and a short email is drafted around it.",
  },
  {
    verb: "Approve",
    body: "Nothing leaves your Gmail until you say so. Sends are spaced out and capped, and replies are tracked for you.",
  },
];

export function Method() {
  return (
    <section id="method" className="relative">
      <div className="mx-auto grid w-full max-w-[1240px] gap-12 px-4 py-24 sm:px-6 md:grid-cols-[0.9fr_1.1fr] md:gap-16 md:py-36">
        <div className="md:sticky md:top-28 md:self-start">
          <p className={eyebrow}>The method</p>
          <h2 className="mt-4 text-4xl leading-[1.02] font-semibold tracking-[-0.04em] md:text-5xl">
            How a case gets solved.
          </h2>
          <div className="paget-tonal-plate mt-10 hidden max-w-sm [mask-image:radial-gradient(ellipse_52%_54%_at_52%_50%,black_45%,transparent_100%)] md:block">
            <Image
              src={portrait}
              alt="Sidney Paget's portrait of Holmes, pipe in hand, thinking."
              sizes="(min-width: 768px) 24rem, 0px"
              placeholder="blur"
              className="h-auto w-full"
            />
          </div>
          <CanonLine {...CANON.data} className="mt-6" />
        </div>

        <ol className="flex flex-col">
          {STEPS.map((step) => (
            <Reveal
              as="li"
              key={step.verb}
              className="group border-b py-10 first:pt-0 last:border-b-0 md:py-14"
            >
              <h3 className="group-hover:text-brand-ink text-3xl font-semibold tracking-[-0.03em] transition-colors duration-500 md:text-[2.6rem]">
                {step.verb}
              </h3>
              <p className="text-muted-foreground mt-3 max-w-[46ch] text-lg leading-relaxed">
                {step.body}
              </p>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* --- What it handles: bento ---------------------------------------------------------------- */

function ResumePreview() {
  return (
    <div
      aria-hidden="true"
      className="bg-surface ring-foreground/[0.07] shadow-lift mt-8 rounded-2xl p-5 ring-1"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="bg-success/12 text-success rounded-md px-1.5 py-0.5 font-medium">
          ATS check passed
        </span>
        <span className="bg-muted rounded-md px-1.5 py-0.5 font-medium">
          One page
        </span>
        <span className="text-muted-foreground ml-auto font-mono">
          Firstname_Lastname_Resume.pdf
        </span>
      </div>
      <div className="mt-4 flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground line-through decoration-[1px]">
          Made the search API faster with Redis caching, cutting p95 latency by
          30%.
        </p>
        <p className="border-brand border-l-2 pl-3">
          Cut p95 latency of a REST API by 30% with Redis caching.
        </p>
        <p className="text-muted-foreground text-xs">
          Same facts, the posting&apos;s own words. New tools or numbers are
          rejected.
        </p>
      </div>
    </div>
  );
}

function TimelinePreview() {
  const rows = [
    ["Sent", "Tue 10:42"],
    ["Reply received", "Wed 09:15"],
    ["Outcome", "Referred"],
  ];
  return (
    <ol aria-hidden="true" className="mt-6 flex flex-col gap-3">
      {rows.map(([label, value], i) => (
        <li key={label} className="flex items-center gap-3 text-sm">
          <span
            className={`size-2 rounded-full ${i === 2 ? "bg-brand" : "bg-foreground/30"}`}
          />
          <span className="font-medium">{label}</span>
          <span className="text-muted-foreground ml-auto font-mono text-xs">
            {value}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function Bento() {
  return (
    <section className="mx-auto w-full max-w-[1240px] px-4 py-24 sm:px-6 md:py-32">
      <Reveal>
        <h2 className="max-w-[18ch] text-4xl leading-[1.02] font-semibold tracking-[-0.04em] md:text-5xl">
          The tedious parts, handled with care.
        </h2>
      </Reveal>
      <div className="mt-14 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Reveal className="bg-muted/60 ring-foreground/[0.06] rounded-[1.75rem] p-7 ring-1 md:col-span-2 md:row-span-2 md:p-9">
          <h3 className="text-2xl font-semibold tracking-tight">
            A resume tailored to each role. Nothing invented.
          </h3>
          <p className="text-muted-foreground mt-3 max-w-[52ch] leading-relaxed">
            Your own bullets, chosen and reordered for the posting. A checker
            refuses anything that isn&apos;t on your master resume, and every
            PDF is parsed the way a hiring system would.
          </p>
          <ResumePreview />
        </Reveal>

        <Reveal
          delay={0.08}
          className="bg-brand/15 ring-brand/25 rounded-[1.75rem] p-7 ring-1"
        >
          <h3 className="text-xl font-semibold tracking-tight">
            The right person, verified
          </h3>
          <p className="text-muted-foreground mt-2 leading-relaxed">
            A founder at a startup, an engineering lead elsewhere. Addresses are
            checked before anything is written.
          </p>
        </Reveal>

        <Reveal
          delay={0.14}
          className="bg-surface ring-foreground/[0.07] shadow-soft rounded-[1.75rem] p-7 ring-1"
        >
          <p className="tabular font-mono text-5xl font-semibold tracking-tight">
            ₹0
          </p>
          <h3 className="mt-3 text-xl font-semibold tracking-tight">
            Runs on free tiers
          </h3>
          <p className="text-muted-foreground mt-2 leading-relaxed">
            Your own Gemini and Hunter keys, your own Gmail. Nothing to pay.
          </p>
        </Reveal>

        <Reveal
          delay={0.06}
          className="bg-surface ring-foreground/[0.07] shadow-soft rounded-[1.75rem] p-7 ring-1 md:col-span-2"
        >
          <div className="grid gap-6 md:grid-cols-2 md:items-end">
            <div>
              <h3 className="text-xl font-semibold tracking-tight">
                Replies, tracked. One follow-up, never two.
              </h3>
              <p className="text-muted-foreground mt-2 leading-relaxed">
                Replies, bounces and opt-outs are read from the thread, so you
                always know where each case stands.
              </p>
            </div>
            <TimelinePreview />
          </div>
        </Reveal>

        <Reveal
          delay={0.12}
          className="bg-foreground text-background dark:bg-surface dark:text-foreground dark:ring-brand/25 flex flex-col justify-between rounded-[1.75rem] p-7 dark:ring-1"
        >
          <blockquote className="font-serif text-2xl leading-snug italic">
            &ldquo;{CANON.littleThings.text}&rdquo;
          </blockquote>
          <p className="text-background/60 dark:text-muted-foreground mt-6 text-xs">
            {CANON.littleThings.source}
          </p>
        </Reveal>
      </div>
    </section>
  );
}

/* --- Open outreach -------------------------------------------------------------------------- */

const ASKS = [
  ["A founder", "Is the team open to taking an intern?"],
  ["An engineering lead", "Would you have 15 minutes, or pass my resume on?"],
  ["A recruiter", "Are there openings coming up I should watch for?"],
];

export function OpenOutreach() {
  return (
    <section id="open-outreach" className="relative overflow-hidden">
      <div className="mx-auto grid w-full max-w-[1240px] items-center gap-12 px-4 py-24 sm:px-6 md:grid-cols-[1fr_1.05fr] md:gap-20 md:py-32">
        <Reveal className="order-2 md:order-1">
          <div className="mx-auto max-w-[520px] [mask-image:radial-gradient(ellipse_66%_64%_at_54%_46%,black_60%,transparent_96%)]">
            <Image
              src={greek}
              alt="Sidney Paget's illustration for The Greek Interpreter: Holmes, pipe raised, talking with Watson."
              sizes="(min-width: 768px) 40vw, 90vw"
              placeholder="blur"
              className="paget h-auto w-full"
            />
          </div>
        </Reveal>
        <div className="order-1 md:order-2">
          <Reveal>
            <h2 className="text-4xl leading-[1.02] font-semibold tracking-[-0.04em] md:text-5xl">
              No posting? Less of a crowd.
            </h2>
            <p className="text-muted-foreground mt-5 max-w-[48ch] text-lg leading-relaxed">
              Name the kind of company you&apos;d like to work at. Sherlock
              reads their site and asks the right person a small question. It
              never pretends there&apos;s an opening.
            </p>
          </Reveal>
          <dl className="mt-10 flex flex-col">
            {ASKS.map(([who, ask], i) => (
              <Reveal
                key={who}
                delay={0.06 * i}
                className="grid gap-1 border-t py-5 sm:grid-cols-[11rem_1fr] sm:gap-6"
              >
                <dt className="text-muted-foreground text-sm">{who}</dt>
                <dd className="font-serif text-xl italic">{ask}</dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

/* --- Manifesto: the quote reads itself as you scroll ------------------------------------------ */

function Word({
  word,
  index,
  total,
  progress,
}: {
  word: string;
  index: number;
  total: number;
  progress: MotionValue<number>;
}) {
  const start = index / total;
  const opacity = useTransform(progress, [start, start + 1 / total], [0.14, 1]);
  return (
    <motion.span style={{ opacity }} className="inline-block">
      {word}&nbsp;
    </motion.span>
  );
}

export function Manifesto() {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.5"],
  });
  const words = CANON.data.text.split(" ");

  return (
    <section className="px-4 py-28 sm:px-6 md:py-40">
      <div ref={ref} className="mx-auto max-w-4xl text-center">
        <blockquote className="font-serif text-4xl leading-[1.15] italic md:text-6xl">
          <span aria-hidden="true">&ldquo;</span>
          {reduce ? (
            CANON.data.text
          ) : (
            <>
              <span className="sr-only">{CANON.data.text}</span>
              <span aria-hidden="true">
                {words.map((word, i) => (
                  <Word
                    key={`${word}-${i}`}
                    word={word}
                    index={i}
                    total={words.length}
                    progress={scrollYProgress}
                  />
                ))}
              </span>
            </>
          )}
          <span aria-hidden="true">&rdquo;</span>
        </blockquote>
        <p className="text-muted-foreground mx-auto mt-8 max-w-[44ch] text-lg leading-relaxed">
          So Sherlock reads the posting before it writes a word, and you read
          the email before it&apos;s sent.
        </p>
      </div>
    </section>
  );
}

/* --- Rules it can't break ------------------------------------------------------------------- */

const RULES: { figure: string; title: string; body: string; wide?: boolean }[] =
  [
    {
      figure: "0",
      title: "emails without your approval",
      body: "Approval is checked again at the moment of sending. Edit a draft after approving and it waits for you again.",
      wide: true,
    },
    {
      figure: "15",
      title: "sends a day by default",
      body: "Spaced minutes apart inside your working hours. You can raise it to 30, never higher.",
    },
    {
      figure: "30",
      title: "days between emails to one person",
      body: "Across everyone using Sherlock, so friends never pile onto the same manager.",
    },
    {
      figure: "1",
      title: "follow-up, at most",
      body: "Short, in the same thread, and only if there was no reply.",
    },
    {
      figure: "1",
      title: "page, ATS-checked",
      body: "Every PDF is read back by a parser before it can be attached.",
    },
    {
      figure: "",
      title: "A way out in every email",
      body: "An opt-out line in every message. Reply “remove me” and that address is never contacted again, by anyone.",
      wide: true,
    },
  ];

export function Rules() {
  return (
    <section id="rules" className="bg-muted/40 border-y">
      <div className="mx-auto w-full max-w-[1240px] px-4 py-24 sm:px-6 md:py-32">
        <Reveal>
          <p className={eyebrow}>Rules it can&apos;t break</p>
          <h2 className="mt-4 max-w-[20ch] text-4xl leading-[1.02] font-semibold tracking-[-0.04em] md:text-5xl">
            Built so it can&apos;t embarrass you.
          </h2>
        </Reveal>
        <div className="mt-14 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {RULES.map((rule, i) => (
            <Reveal
              key={rule.title}
              delay={0.05 * (i % 3)}
              className={`bg-surface ring-foreground/[0.07] shadow-soft flex flex-col gap-4 rounded-[1.75rem] p-7 ring-1 ${rule.wide ? (i === 0 ? "lg:col-span-2" : "md:col-span-2 lg:col-span-3") : ""}`}
            >
              {rule.figure ? (
                <p className="flex items-baseline gap-3">
                  <span className="tabular font-mono text-5xl font-semibold tracking-tight">
                    {rule.figure}
                  </span>
                  <span className="text-lg font-medium tracking-tight">
                    {rule.title}
                  </span>
                </p>
              ) : (
                <p className="font-serif text-3xl italic">{rule.title}</p>
              )}
              <p className="text-muted-foreground max-w-[60ch] leading-relaxed">
                {rule.body}
              </p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --- Closing --------------------------------------------------------------------------------- */

export function Closing() {
  return (
    <section className="px-4 py-24 sm:px-6 md:py-32">
      <Reveal className="bg-surface ring-foreground/[0.07] shadow-lift relative mx-auto max-w-[1240px] overflow-hidden rounded-[2rem] px-6 py-20 text-center ring-1 md:py-28">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 -top-1/2 mx-auto h-full w-3/4 rounded-full blur-3xl"
          style={{
            background:
              "radial-gradient(closest-side, color-mix(in oklch, var(--brand) 30%, transparent), transparent)",
          }}
        />
        <div className="relative">
          <h2 className="text-5xl leading-[0.98] font-semibold tracking-[-0.045em] md:text-7xl">
            The game is afoot.
          </h2>
          <p className="text-muted-foreground mx-auto mt-5 max-w-[40ch] text-lg">
            Sign in with the Google account you were invited with.
          </p>
          <div className="mt-9 flex justify-center">
            <PrimaryAction size="lg" />
          </div>
        </div>
      </Reveal>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t">
      <div className="mx-auto grid w-full max-w-[1240px] gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1fr_auto]">
        <div className="max-w-md">
          <Wordmark />
          <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
            Self-hosted for a small group of friends. Invite only, no public
            sign-up.
          </p>
          <p className="text-muted-foreground/80 mt-6 text-xs leading-relaxed">
            Illustrations by Sidney Paget (1860-1908) for The Strand Magazine.
            Public domain, via Wikimedia Commons.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-col gap-2.5 text-sm">
          <a
            className="text-muted-foreground hover:text-foreground"
            href="#method"
          >
            How it works
          </a>
          <a
            className="text-muted-foreground hover:text-foreground"
            href="#open-outreach"
          >
            Open outreach
          </a>
          <a
            className="text-muted-foreground hover:text-foreground"
            href="#rules"
          >
            Safety
          </a>
          <Link
            className="text-muted-foreground hover:text-foreground"
            href="/login"
          >
            Sign in
          </Link>
        </nav>
      </div>
      <div className="text-muted-foreground/70 mx-auto flex w-full max-w-[1240px] justify-between px-4 pb-8 text-xs sm:px-6">
        <span>221B, figuratively.</span>
        <span className="font-serif italic">Elementary.</span>
      </div>
    </footer>
  );
}
