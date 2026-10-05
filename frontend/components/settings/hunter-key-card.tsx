"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api";
import {
  useDeleteHunterKey,
  useHunterKey,
  useSaveHunterKey,
} from "@/lib/queries";

export function HunterKeyCard() {
  const status = useHunterKey();
  const save = useSaveHunterKey();
  const remove = useDeleteHunterKey();
  const [key, setKey] = useState("");
  const data = status.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Hunter API key
          {data?.configured ? (
            <Badge>Connected</Badge>
          ) : data?.owner_fallback_allowed ? (
            <Badge variant="secondary">Using the owner&apos;s key</Badge>
          ) : (
            <Badge variant="destructive">Not set</Badge>
          )}
        </CardTitle>
        <CardDescription>
          Sherlock finds who to email (and checks the address) with your own
          free Hunter account, about 50 credits a month. Create a key at{" "}
          <a
            className="underline"
            href="https://hunter.io/api-keys"
            target="_blank"
            rel="noreferrer"
          >
            hunter.io/api-keys
          </a>
          . Contacts found for a company are reused for 60 days at no cost.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {data && (
          <p className="text-muted-foreground text-sm">
            Lookups this month: {data.searches_this_month} of{" "}
            {data.monthly_limit}.
            {data.verified_at &&
              ` Key verified ${new Date(data.verified_at).toLocaleString()}; it's stored encrypted and never shown again.`}
          </p>
        )}
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(key.trim(), { onSuccess: () => setKey("") });
          }}
        >
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="hunter-key">
              {data?.configured ? "Replace key" : "API key"}
            </Label>
            <Input
              id="hunter-key"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            disabled={key.trim().length < 10 || save.isPending}
          >
            {save.isPending ? "Checking…" : "Check and save"}
          </Button>
          {data?.configured && (
            <Button
              type="button"
              variant="outline"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Remove
            </Button>
          )}
        </form>
        {save.isError && (
          <p className="text-destructive text-sm">{errorMessage(save.error)}</p>
        )}
      </CardContent>
    </Card>
  );
}
