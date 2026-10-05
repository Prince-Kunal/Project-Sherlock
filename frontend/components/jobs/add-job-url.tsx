"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { useAddJobUrl } from "@/lib/queries";

export function AddJobUrl() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const add = useAddJobUrl();

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Plus /> Add job URL
      </Button>
    );
  }

  return (
    <form
      className="flex w-full flex-col gap-2 sm:w-auto"
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate(url.trim(), {
          onSuccess: () => {
            setUrl("");
            setOpen(false);
          },
        });
      }}
    >
      <div className="flex gap-2">
        <Input
          autoFocus
          type="url"
          required
          aria-label="Job posting URL"
          placeholder="https://jobs.lever.co/company/…"
          className="sm:w-96"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button type="submit" disabled={add.isPending}>
          {add.isPending ? "Adding…" : "Add"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        Greenhouse, Lever and Ashby links are read directly; other career pages
        use one Gemini request.
      </p>
      {add.isError && (
        <p className="text-destructive text-sm">{errorMessage(add.error)}</p>
      )}
    </form>
  );
}
