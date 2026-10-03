"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/review", label: "Review queue" },
  { href: "/jobs", label: "Jobs feed" },
  { href: "/tracker", label: "Outreach tracker" },
  { href: "/profile", label: "Profile and resume" },
  { href: "/settings", label: "Settings" },
] as const;

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();
  const logout = useLogout();

  const unauthenticated =
    me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace("/login");
  }, [unauthenticated, router]);

  if (me.isPending || unauthenticated) {
    return (
      <div className="text-muted-foreground flex flex-1 items-center justify-center">
        Loading…
      </div>
    );
  }

  if (me.isError) {
    return (
      <div className="text-destructive flex flex-1 items-center justify-center">
        Could not reach the Sherlock API.
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link href="/review" className="text-lg font-semibold tracking-tight">
            Sherlock
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground hidden sm:inline">
              {me.data.email}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                logout.mutate(undefined, {
                  onSuccess: () => router.replace("/login"),
                })
              }
            >
              Log out
            </Button>
          </div>
        </div>
        <nav
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4"
          aria-label="Sections"
        >
          {TABS.map((tab) => {
            const active = pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors",
                  active
                    ? "border-foreground text-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground border-transparent",
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
