"use client";

import { useEffect } from "react";
import { toast } from "sonner";

import { CANON, randomQuote } from "@/lib/canon";

const KONAMI = [
  "arrowup",
  "arrowup",
  "arrowdown",
  "arrowdown",
  "arrowleft",
  "arrowright",
  "arrowleft",
  "arrowright",
  "b",
  "a",
];

function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

const CODES: Record<string, () => void> = {
  elementary: () =>
    toast("Elementary.", {
      description:
        "Holmes never says “Elementary, my dear Watson” in any of the sixty stories. He says each half, never together.",
    }),
  "221b": () => {
    const root = document.documentElement;
    root.setAttribute("data-gaslight", "");
    window.setTimeout(() => root.removeAttribute("data-gaslight"), 2600);
    toast("221B Baker Street.", {
      description:
        "Mrs. Hudson has turned up the gas. Mind the Persian slipper.",
    });
  },
  moriarty: () =>
    toast("The Napoleon of crime.", {
      description:
        "He'd never pass the send-time checks. No approval, no email. Not even for him.",
    }),
  watson: () => {
    const q = randomQuote();
    toast(`“${q.text}”`, { description: q.source });
  },
};

/** Hidden extras for the curious: a note in the console, typed codes and the Konami code. */
export function EasterEggs() {
  useEffect(() => {
    try {
      if (!sessionStorage.getItem("sherlock-console")) {
        sessionStorage.setItem("sherlock-console", "1");
        console.log(
          "%c  ◯\n   ╲  Sherlock\n%c“%s”\n%c%s\n\nYou found the console. Try typing elementary, 221b, watson or moriarty outside a text box (anywhere but the review queue, where single keys approve drafts).",
          "color:#e0a23c;font:600 14px ui-monospace,monospace",
          "font:italic 13px Georgia,serif",
          CANON.observe.text,
          "color:#8a8f98;font:12px system-ui",
          `Sherlock Holmes, ${CANON.observe.source}`,
        );
      }
    } catch {
      // storage unavailable: skip the console note
    }

    let buffer = "";
    let konami = 0;
    const onKey = (event: KeyboardEvent) => {
      // The review queue's single-key shortcuts approve and skip drafts ("a", "s"): typed codes
      // must never run there, or "elementary" would approve an email.
      if (window.location.pathname.startsWith("/review")) return;
      if (
        typing(event.target) ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      )
        return;
      const key = event.key.toLowerCase();

      konami = key === KONAMI[konami] ? konami + 1 : key === KONAMI[0] ? 1 : 0;
      if (konami === KONAMI.length) {
        konami = 0;
        const root = document.documentElement;
        const on = !root.hasAttribute("data-strand");
        root.toggleAttribute("data-strand", on);
        try {
          if (on) localStorage.setItem("sherlock-strand", "1");
          else localStorage.removeItem("sherlock-strand");
        } catch {
          // not persisted
        }
        toast(on ? "The Strand Magazine, 1891." : "Back to the present.", {
          description: on
            ? "Printed in sepia, as Sidney Paget drew it. Enter the code again to return."
            : undefined,
        });
        return;
      }

      if (key.length !== 1) return;
      buffer = (buffer + key).slice(-12);
      for (const [code, run] of Object.entries(CODES)) {
        if (buffer.endsWith(code)) {
          buffer = "";
          run();
          break;
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return null;
}
