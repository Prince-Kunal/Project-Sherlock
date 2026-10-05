"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { useDeleteLlmKey, useLlmKey, useSaveLlmKey } from "@/lib/queries";

export function LlmKeyCard() {
  const status = useLlmKey();
  const save = useSaveLlmKey();
  const remove = useDeleteLlmKey();
  const [key, setKey] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Gemini API key
          {status.data?.configured ? (
            <Badge>Connected</Badge>
          ) : (
            <Badge variant="destructive">Not set</Badge>
          )}
        </CardTitle>
        <CardDescription>
          Sherlock uses your own free Gemini key, so your daily limit isn&apos;t
          shared with anyone. Create one at{" "}
          <a
            className="underline"
            href="https://aistudio.google.com/apikey"
            target="_blank"
            rel="noreferrer"
          >
            aistudio.google.com/apikey
          </a>
          .
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {status.data && (
          <Alert>
            <AlertTitle>About the free tier</AlertTitle>
            <AlertDescription>{status.data.notice}</AlertDescription>
          </Alert>
        )}
        {status.data?.verified_at && (
          <p className="text-muted-foreground text-sm">
            Verified {new Date(status.data.verified_at).toLocaleString()}. The
            key is stored encrypted and is never shown again.
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
            <Label htmlFor="gemini-key">
              {status.data?.configured ? "Replace key" : "API key"}
            </Label>
            <Input
              id="gemini-key"
              type="password"
              autoComplete="off"
              placeholder="AIza…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            disabled={key.trim().length < 10 || save.isPending}
          >
            {save.isPending ? "Verifying…" : "Verify and save"}
          </Button>
          {status.data?.configured && (
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
