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
  useApolloKey,
  useDeleteApolloKey,
  useSaveApolloKey,
} from "@/lib/queries";

export function ApolloKeyCard() {
  const status = useApolloKey();
  const save = useSaveApolloKey();
  const remove = useDeleteApolloKey();
  const [key, setKey] = useState("");
  const data = status.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Apollo API key
          {data?.configured ? (
            <Badge>Connected</Badge>
          ) : (
            <Badge variant="secondary">Optional</Badge>
          )}
        </CardTitle>
        <CardDescription>
          With a key, people are searched on Apollo first and Hunter only
          verifies the address, which saves Hunter credits. Apollo&apos;s free
          plan only allows search for accounts registered with a work email.
          Without a key, Hunter does everything.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {data?.configured && (
          <p className="text-muted-foreground text-sm">
            Apollo searches this month: {data.searches_this_month}.
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
            <Label htmlFor="apollo-key">
              {data?.configured ? "Replace key" : "API key"}
            </Label>
            <Input
              id="apollo-key"
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
