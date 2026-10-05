"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

/** A list of short strings edited as removable chips. Enter or comma adds; Backspace on empty removes. */
export function ChipsInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  lowercase = false,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  ariaLabel: string;
  lowercase?: boolean;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const items = raw
      .split(",")
      .map((s) => (lowercase ? s.trim().toLowerCase() : s.trim()))
      .filter((s) => s && !value.includes(s));
    if (items.length) onChange([...value, ...items]);
    setDraft("");
  };

  return (
    <div className="border-input focus-within:ring-ring/50 flex min-h-8 flex-wrap items-center gap-1 rounded-lg border px-1.5 py-1 focus-within:ring-3">
      {value.map((item) => (
        <Badge key={item} variant="secondary" className="gap-1 pr-1">
          {item}
          <button
            type="button"
            aria-label={`Remove ${item}`}
            className="hover:text-foreground text-muted-foreground rounded-sm"
            onClick={() => onChange(value.filter((v) => v !== item))}
          >
            <X className="size-3" />
          </button>
        </Badge>
      ))}
      <Input
        aria-label={ariaLabel}
        value={draft}
        placeholder={value.length ? undefined : placeholder}
        className="h-6 min-w-24 flex-1 border-0 px-1 shadow-none focus-visible:ring-0"
        onChange={(e) => {
          if (e.target.value.includes(",")) add(e.target.value);
          else setDraft(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft && add(draft)}
      />
    </div>
  );
}
