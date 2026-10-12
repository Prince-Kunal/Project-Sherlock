"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { useAddCompany, useCompanySearch } from "@/lib/queries";
import type { CompanyBrief } from "@/lib/types";

/** Pick companies by name or domain; a website that isn't known yet can be added. */
export function CompanyPicker({
  value,
  onChange,
  ariaLabel,
  placeholder,
}: {
  value: CompanyBrief[];
  onChange: (next: CompanyBrief[]) => void;
  ariaLabel: string;
  placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const search = useCompanySearch(q);
  const add = useAddCompany();
  const chosen = new Set(value.map((c) => c.id));
  const results = (search.data ?? []).filter((c) => !chosen.has(c.id));
  const looksLikeSite = /\.[a-z]{2,}/i.test(q.trim());

  const pick = (company: CompanyBrief) => {
    onChange([...value, company]);
    setQ("");
  };

  return (
    <div className="flex flex-col gap-1.5">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((c) => (
            <Badge key={c.id} variant="secondary" className="gap-1 pr-1">
              {c.name}
              {c.domain && (
                <span className="text-muted-foreground">({c.domain})</span>
              )}
              <button
                type="button"
                aria-label={`Remove ${c.name}`}
                className="hover:text-foreground text-muted-foreground rounded-sm"
                onClick={() => onChange(value.filter((x) => x.id !== c.id))}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        aria-label={ariaLabel}
        value={q}
        placeholder={placeholder ?? "Search by name, or type a website"}
        onChange={(e) => setQ(e.target.value)}
      />
      {q.trim().length >= 2 && (
        <div className="flex flex-wrap gap-1">
          {results.map((c) => (
            <Button
              key={c.id}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => pick(c)}
            >
              <Plus /> {c.name}
              {c.domain && (
                <span className="text-muted-foreground">{c.domain}</span>
              )}
            </Button>
          ))}
          {looksLikeSite && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={add.isPending}
              onClick={() => add.mutate(q.trim(), { onSuccess: pick })}
            >
              <Plus /> Add {q.trim()}
            </Button>
          )}
          {search.isSuccess && results.length === 0 && !looksLikeSite && (
            <span className="text-muted-foreground text-xs">
              No match. Type the company&apos;s website to add it.
            </span>
          )}
        </div>
      )}
      {add.isError && (
        <p className="text-destructive text-sm">{errorMessage(add.error)}</p>
      )}
    </div>
  );
}
