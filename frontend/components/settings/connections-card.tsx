"use client";

import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import {
  useConnections,
  useDeleteConnections,
  useUploadConnections,
} from "@/lib/queries";

/** Phase 10 warm paths: the user's own connections list, to flag companies where they know someone. */
export function ConnectionsCard() {
  const summary = useConnections();
  const upload = useUploadConnections();
  const remove = useDeleteConnections();
  const input = useRef<HTMLInputElement>(null);
  const data = summary.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>People you know</CardTitle>
        <CardDescription>
          Upload your connections and Sherlock flags jobs and drafts at
          companies where you already know someone, and who went to your
          college. Use LinkedIn&apos;s own export (Settings, Data privacy, Get a
          copy of your data, Connections) or any CSV with name and company
          columns, plus school if you have it. The list stays private to you, is
          never sent to the AI, and nobody on it is ever emailed.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {data && data.count > 0 && (
          <p className="text-sm">
            {data.count} people at {data.companies} companies
            {data.alumni > 0 && `, ${data.alumni} from your college`}.
            {data.uploaded_at &&
              ` Uploaded ${new Date(data.uploaded_at).toLocaleDateString()}.`}
          </p>
        )}
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            disabled={upload.isPending}
            onClick={() => input.current?.click()}
          >
            {upload.isPending
              ? "Reading…"
              : data && data.count > 0
                ? "Upload a new list"
                : "Upload connections CSV"}
          </Button>
          {data && data.count > 0 && (
            <Button
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Remove the list
            </Button>
          )}
        </div>
        {(upload.isError || remove.isError) && (
          <p className="text-destructive text-sm">
            {errorMessage(upload.error ?? remove.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
