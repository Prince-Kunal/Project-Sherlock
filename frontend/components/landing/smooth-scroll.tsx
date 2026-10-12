"use client";

import { ReactLenis } from "lenis/react";
import { useReducedMotion } from "motion/react";
import { useEffect } from "react";

/**
 * Lenis inertia scrolling for the landing page only (the app keeps native scroll). Anchor links
 * glide to their section. Off entirely under prefers-reduced-motion.
 */
export function SmoothScroll({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();

  // A small one: leave the tab and the title calls you back.
  useEffect(() => {
    const original = document.title;
    const onVisibility = () => {
      document.title = document.hidden
        ? "Come, Watson. The game is afoot."
        : original;
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      document.title = original;
    };
  }, []);

  if (reduce) return <>{children}</>;
  return (
    <ReactLenis
      root
      options={{
        lerp: 0.09,
        wheelMultiplier: 0.95,
        anchors: { offset: -24 },
        autoRaf: true,
      }}
    >
      {children}
    </ReactLenis>
  );
}
