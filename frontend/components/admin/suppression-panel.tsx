"use client";

import { useState } from "react";

import { Cell, DataTable } from "@/components/admin/table";
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
import { useAddSuppression, useSuppressionList } from "@/lib/queries";
import type { SuppressionEntry } from "@/lib/types";

const REASONS: Record<SuppressionEntry["reason"], string> = {
  opt_out: "Asked not to be emailed",
  bounce: "Bounced",
  manual: "Added by hand",
};

/** The global do-not-contact list: nobody using Sherlock may email these addresses. */
export function SuppressionPanel() {
  const [q, setQ] = useState("");
  const list = useSuppressionList(q.trim());
  const add = useAddSuppression();
  const [email, setEmail] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Do-not-contact list</CardTitle>
        <CardDescription>
          Shared by everyone: an address here is never emailed by anyone using
          Sherlock. Opt-out replies and bounces are added automatically. Add an
          address by hand if someone asked another way.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(email.trim(), { onSuccess: () => setEmail("") });
          }}
        >
          <Input
            type="email"
            required
            aria-label="Address to add"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" disabled={add.isPending}>
            Add to list
          </Button>
        </form>
        {add.isError && (
          <p className="text-destructive text-sm">{errorMessage(add.error)}</p>
        )}
        <Input
          type="search"
          aria-label="Search the list"
          placeholder="Search addresses"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {list.data && (
          <>
            <p className="text-muted-foreground text-sm">
              {list.data.total} address{list.data.total === 1 ? "" : "es"}
              {q.trim() && " match"}
            </p>
            {list.data.items.length > 0 && (
              <DataTable head={["Address", "Why", "Since"]}>
                {list.data.items.map((row) => (
                  <tr key={row.email}>
                    <Cell className="break-all">{row.email}</Cell>
                    <Cell>
                      <Badge
                        variant={
                          row.reason === "opt_out" ? "secondary" : "outline"
                        }
                      >
                        {REASONS[row.reason]}
                      </Badge>
                    </Cell>
                    <Cell className="text-muted-foreground whitespace-nowrap">
                      {new Date(row.created_at).toLocaleDateString()}
                    </Cell>
                  </tr>
                ))}
              </DataTable>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
