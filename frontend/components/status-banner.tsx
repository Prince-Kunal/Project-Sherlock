"use client";

import { AlertTriangle, Gauge, PauseCircle } from "lucide-react";
import Link from "next/link";

import { googleSignInUrl } from "@/lib/auth";
import { useGmailStatus, useQuota } from "@/lib/queries";

/** Shown on every page when sending can't happen (Gmail needs reconnecting, or the user paused) or
 * when this month's quota is used up. */
export function StatusBanner() {
  const gmail = useGmailStatus();
  const quota = useQuota();
  const status = gmail.data;
  if (!status) return null;

  let message: React.ReactNode = null;
  if (status.google_sign_in && status.needs_reauth) {
    message = (
      <>
        Google ended Sherlock&apos;s access to your Gmail (this happens about
        once a week while the app is in testing). Sending is paused until you{" "}
        <a className="font-medium underline" href={googleSignInUrl("/review")}>
          reconnect Gmail
        </a>
        .
      </>
    );
  } else if (status.google_sign_in && status.missing_permissions) {
    message = (
      <>
        Sherlock can&apos;t send or track email: the Gmail boxes weren&apos;t
        ticked on Google&apos;s screen.{" "}
        <a className="font-medium underline" href={googleSignInUrl("/review")}>
          Connect Gmail again
        </a>{" "}
        and tick both.
      </>
    );
  } else if (status.google_sign_in && !status.connected) {
    message = (
      <>
        Gmail isn&apos;t connected, so approved emails won&apos;t go out.{" "}
        <a className="font-medium underline" href={googleSignInUrl("/review")}>
          Connect Gmail
        </a>
        .
      </>
    );
  }

  return (
    <>
      {message && (
        <div className="border-b border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
          <p className="mx-auto flex max-w-6xl items-start gap-2 px-4 py-2 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{message}</span>
          </p>
        </div>
      )}
      {quota.data?.message && (
        <div className="border-b border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
          <p className="mx-auto flex max-w-6xl items-start gap-2 px-4 py-2 text-sm">
            <Gauge className="mt-0.5 size-4 shrink-0" />
            <span>{quota.data.message}</span>
          </p>
        </div>
      )}
      {status.paused && (
        <div className="bg-muted border-b">
          <p className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 text-sm">
            <PauseCircle className="size-4 shrink-0" />
            <span>
              Sherlock is paused: no new drafts and nothing is sent.{" "}
              <Link className="font-medium underline" href="/settings">
                Resume in Settings
              </Link>
              .
            </span>
          </p>
        </div>
      )}
    </>
  );
}
