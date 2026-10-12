"use client";

import { X } from "lucide-react";
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
import { errorMessage } from "@/lib/api";
import { useMe } from "@/lib/auth";
import {
  useAllowedEmails,
  useAllowEmail,
  useRemoveAllowedEmail,
} from "@/lib/queries";

/** Admins only: who may sign in. */
export function AllowedPeopleCard() {
  const me = useMe();
  const isAdmin = me.data?.is_admin ?? false;
  const list = useAllowedEmails(isAdmin);
  const allow = useAllowEmail();
  const remove = useRemoveAllowedEmail();
  const [email, setEmail] = useState("");
  if (!isAdmin) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Who can sign in</CardTitle>
        <CardDescription>
          Only these Google accounts can use Sherlock. While the Google app is
          in testing, also add each person as a test user in the Google Cloud
          console, or Google will refuse their sign-in.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            allow.mutate(email.trim(), { onSuccess: () => setEmail("") });
          }}
        >
          <Input
            type="email"
            required
            aria-label="Email to allow"
            placeholder="friend@gmail.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" disabled={allow.isPending}>
            Add
          </Button>
        </form>
        <ul className="flex flex-col divide-y rounded-lg border text-sm">
          {list.data?.map((row) => (
            <li
              key={row.email}
              className="flex items-center justify-between gap-2 px-3 py-2"
            >
              <span className="flex items-center gap-2">
                {row.email}
                {row.signed_up && <Badge variant="secondary">signed up</Badge>}
              </span>
              {row.email !== me.data?.email && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove ${row.email}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(row.email)}
                >
                  <X />
                </Button>
              )}
            </li>
          ))}
          {list.data?.length === 0 && (
            <li className="text-muted-foreground px-3 py-2">
              Nobody yet besides ADMIN_EMAILS.
            </li>
          )}
        </ul>
        {(allow.isError || remove.isError) && (
          <p className="text-destructive text-sm">
            {errorMessage(allow.error ?? remove.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
