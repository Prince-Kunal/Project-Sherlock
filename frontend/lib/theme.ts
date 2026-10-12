"use client";

import { useCallback, useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "sherlock-theme";

/**
 * Runs in <head> before first paint (see Next's "preventing flash before hydration" guide):
 * applies the saved choice, or the OS preference, as the `dark` class on <html>.
 */
export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${KEY}");var d=t==="dark"||((!t||t==="system")&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);if(localStorage.getItem("sherlock-strand"))document.documentElement.setAttribute("data-strand","")}catch(e){}})()`;

function read(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(choice: ThemeChoice) {
  const dark =
    choice === "dark" ||
    (choice === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystem = () => {
    if (read() === "system") apply("system");
  };
  media.addEventListener("change", onSystem);
  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", onSystem);
  };
}

/** The saved theme choice and a setter; follows the OS when the choice is "system". */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const choice = useSyncExternalStore(
    subscribe,
    read,
    (): ThemeChoice => "system",
  );
  const set = useCallback((next: ThemeChoice) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // private mode: the choice lasts for this page only
    }
    apply(next);
    listeners.forEach((l) => l());
  }, []);
  return [choice, set];
}
