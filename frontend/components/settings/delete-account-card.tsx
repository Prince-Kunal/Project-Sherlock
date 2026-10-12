"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

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
import { useMe } from "@/lib/auth";
import { useDeleteAccount } from "@/lib/queries";

/** Phase 9: hard-delete everything Sherlock holds for this user. */
export function DeleteAccountCard() {
  const me = useMe();
  const remove = useDeleteAccount();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const email = me.data?.email ?? "";
  const matches = typed.trim().toLowerCase() === email.toLowerCase();

  return (
    <Card className="ring-destructive/30">
      <CardHeader>
        <CardTitle>Delete my data</CardTitle>
        <CardDescription>
          Removes your account, resumes, matches, targets, drafts, email
          history, keys and files, and revokes Sherlock&apos;s access to your
          Gmail. Emails already sent stay in your Gmail. This can&apos;t be
          undone. Addresses that asked not to be emailed stay on the shared
          do-not-contact list.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!open ? (
          <div>
            <Button variant="destructive" onClick={() => setOpen(true)}>
              Delete my data…
            </Button>
          </div>
        ) : (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              remove.mutate(typed.trim(), {
                onSuccess: () => router.replace("/login?deleted=1"),
              });
            }}
          >
            <Label className="flex flex-col items-stretch gap-1.5 font-normal">
              <span className="text-sm">
                Type <span className="font-medium">{email}</span> to confirm
              </span>
              <Input
                autoComplete="off"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
              />
            </Label>
            <div className="flex gap-2">
              <Button
                type="submit"
                variant="destructive"
                disabled={!matches || remove.isPending}
              >
                {remove.isPending ? "Deleting…" : "Delete everything"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  setTyped("");
                }}
              >
                Cancel
              </Button>
            </div>
            {remove.isError && (
              <p className="text-destructive text-sm">
                {errorMessage(remove.error)}
              </p>
            )}
          </form>
        )}
      </CardContent>
    </Card>
  );
}
