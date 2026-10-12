"use client";

import { Menu } from "@base-ui/react/menu";
import { Check, LogOut, Settings } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { User } from "@/lib/api";
import { useLogout } from "@/lib/auth";
import { type ThemeChoice, useTheme } from "@/lib/theme";

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Match my device" },
  { value: "light", label: "Daylight" },
  { value: "dark", label: "Gaslight" },
];

function initials(user: User): string {
  const name = user.name.trim() || user.email;
  const parts = name.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const itemClass =
  "flex cursor-default items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm outline-none select-none data-highlighted:bg-muted";

export function UserMenu({ user }: { user: User }) {
  const router = useRouter();
  const logout = useLogout();
  const [theme, setTheme] = useTheme();

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label="Account and appearance"
        className="bg-muted text-foreground ring-foreground/10 hover:ring-brand/60 focus-visible:ring-ring/60 flex size-9 items-center justify-center rounded-xl text-xs font-semibold tracking-wide ring-1 transition-[box-shadow] duration-200 outline-none ring-inset focus-visible:ring-3"
      >
        {initials(user)}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={10} align="end" className="z-50">
          <Menu.Popup className="bg-popover text-popover-foreground ring-foreground/10 shadow-lift w-64 origin-(--transform-origin) rounded-2xl p-1.5 ring-1 transition-[transform,opacity] duration-200 ease-(--ease-out-expo) data-ending-style:opacity-0 data-starting-style:scale-[0.97] data-starting-style:opacity-0">
            <div className="px-2.5 pt-2 pb-2.5">
              <p className="truncate text-sm font-medium">
                {user.name || "Signed in"}
              </p>
              <p className="text-muted-foreground truncate text-xs">
                {user.email}
              </p>
            </div>
            <Menu.Separator className="bg-border mx-1 my-1 h-px" />
            <Menu.Group>
              <Menu.GroupLabel className="text-muted-foreground px-2.5 pt-1.5 pb-1 text-xs">
                Appearance
              </Menu.GroupLabel>
              <Menu.RadioGroup
                value={theme}
                onValueChange={(value) => setTheme(value as ThemeChoice)}
              >
                {THEMES.map((t) => (
                  <Menu.RadioItem
                    key={t.value}
                    value={t.value}
                    closeOnClick={false}
                    className={itemClass}
                  >
                    <span className="flex size-4 items-center justify-center">
                      <Menu.RadioItemIndicator>
                        <Check className="text-brand-ink size-4" />
                      </Menu.RadioItemIndicator>
                    </span>
                    {t.label}
                  </Menu.RadioItem>
                ))}
              </Menu.RadioGroup>
            </Menu.Group>
            <Menu.Separator className="bg-border mx-1 my-1 h-px" />
            <Menu.Item className={itemClass} render={<Link href="/settings" />}>
              <Settings className="size-4" /> Settings
            </Menu.Item>
            <Menu.Item
              className={itemClass}
              onClick={() =>
                logout.mutate(undefined, {
                  onSuccess: () => router.replace("/login"),
                })
              }
            >
              <LogOut className="size-4" /> Sign out
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
