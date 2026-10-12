"use client";

import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Wordmark } from "@/components/brand";
import { StatusBanner } from "@/components/status-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { UserMenu } from "@/components/user-menu";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/review", label: "Review queue" },
  { href: "/jobs", label: "Jobs" },
  { href: "/targets", label: "Targets" },
  { href: "/tracker", label: "Tracker" },
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
] as const;
const ADMIN_TAB = { href: "/admin", label: "Admin" } as const;

function Nav({
  id,
  className,
  isAdmin,
}: {
  id: string;
  className?: string;
  isAdmin: boolean;
}) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  const tabs = isAdmin ? [...TABS, ADMIN_TAB] : TABS;
  return (
    <nav aria-label="Sections" className={className}>
      <ul className="bg-muted/70 ring-foreground/[0.06] flex w-max items-center gap-0.5 rounded-full p-1 ring-1 ring-inset">
        {tabs.map((tab) => {
          const active = pathname.startsWith(tab.href);
          return (
            <li key={tab.href} className="relative">
              {active && (
                <motion.span
                  layoutId={`nav-active-${id}`}
                  transition={
                    reduce
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 420, damping: 36 }
                  }
                  className="bg-surface shadow-soft ring-foreground/[0.06] absolute inset-0 rounded-full ring-1"
                />
              )}
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "focus-visible:ring-ring/60 relative block rounded-full px-3.5 py-1.5 text-sm whitespace-nowrap transition-colors duration-200 outline-none focus-visible:ring-3",
                  active
                    ? "text-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const me = useMe();

  const unauthenticated =
    me.error instanceof ApiError && me.error.status === 401;

  const needsOnboarding = me.data !== undefined && !me.data.onboarded;

  useEffect(() => {
    if (unauthenticated) router.replace("/login");
    else if (needsOnboarding) router.replace("/welcome");
  }, [unauthenticated, needsOnboarding, router]);

  if (me.isPending || unauthenticated || needsOnboarding) {
    return (
      <div
        role="status"
        aria-label="Opening your case files"
        className="mx-auto flex w-full max-w-[1240px] flex-col gap-8 px-4 py-6 sm:px-6"
      >
        <div className="flex items-center justify-between">
          <Wordmark />
          <Skeleton className="size-9 rounded-xl" />
        </div>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (me.isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 text-center">
        <Wordmark />
        <p className="text-destructive text-sm">
          Can&apos;t reach the Sherlock API. Is the backend running?
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="bg-background/75 border-border/60 sticky top-0 z-40 border-b backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-[1240px] items-center justify-between gap-4 px-4 sm:px-6">
          <Link
            href="/review"
            className="focus-visible:ring-ring/60 rounded-lg outline-none focus-visible:ring-3"
          >
            <Wordmark />
          </Link>
          <Nav
            id="wide"
            className="hidden lg:block"
            isAdmin={me.data.is_admin}
          />
          <UserMenu user={me.data} />
        </div>
        <div className="[scrollbar-width:none] overflow-x-auto px-4 pb-3 lg:hidden">
          <Nav id="narrow" isAdmin={me.data.is_admin} />
        </div>
      </header>
      <StatusBanner />
      <main
        id="main"
        className="mx-auto w-full max-w-[1240px] flex-1 px-4 pt-8 pb-16 sm:px-6"
      >
        {children}
      </main>
    </div>
  );
}
