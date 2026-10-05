"use client";

import { AlertTriangle, CheckCircle2, UserRoundSearch } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { useFindContact, useSetContact } from "@/lib/queries";
import type { Contact, Match, Outreach } from "@/lib/types";

const ROLE_LABELS: Record<Contact["role_category"], string> = {
  founder: "Founder",
  eng_manager: "Engineering lead",
  engineer: "Engineer",
  recruiter: "Recruiter",
  other: "Contact",
};

const FAILURE_LABELS: Record<string, string> = {
  no_contact: "No suitable contact found",
  contact_key_required: "Add your Hunter key to look up contacts",
  contact_quota: "Your Hunter credits for this month are used up",
  contact_key_invalid: "Hunter rejected your key",
  contact_lookup_limit: "You've used this month's contact lookups",
  contact_provider_error: "Hunter didn't respond properly",
};

/** Phase 5: find who to email for this match, or add them by hand. */
export function ContactPanel({ match }: { match: Match }) {
  const find = useFindContact();
  const outreach = match.outreach;

  if (!outreach) {
    return (
      <div className="mt-2">
        <Button
          variant="outline"
          size="sm"
          disabled={find.isPending}
          onClick={() => find.mutate(match.id)}
          title="Find the best person at this company to ask for a referral"
        >
          <UserRoundSearch />
          {find.isPending ? "Finding contact…" : "Find contact"}
        </Button>
        {find.isError && (
          <p className="text-destructive mt-1 text-sm">
            {errorMessage(find.error)}
          </p>
        )}
      </div>
    );
  }
  return <OutreachContact outreach={outreach} />;
}

function OutreachContact({ outreach }: { outreach: Outreach }) {
  const [editing, setEditing] = useState(false);
  const contact = outreach.contact;
  const failed = outreach.status === "failed";

  return (
    <div className="bg-muted/30 mt-2 rounded-lg border p-3 text-sm">
      {contact && !failed ? (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="font-medium">
              {contact.full_name}
              <span className="text-muted-foreground font-normal">
                {" "}
                · {contact.title ?? ROLE_LABELS[contact.role_category]}
              </span>
            </p>
            <p className="flex items-center gap-1.5">
              {contact.email}
              {contact.verification_status === "valid" ? (
                <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
                  <CheckCircle2 className="size-3.5" /> verified
                </span>
              ) : (
                <span
                  className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400"
                  title="This company's mail server accepts every address, so delivery can't be confirmed."
                >
                  <AlertTriangle className="size-3.5" /> accept-all domain
                </span>
              )}
            </p>
          </div>
          {!editing && (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              Change contact
            </Button>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p>
            <span className="font-medium">
              {FAILURE_LABELS[outreach.failure_reason ?? ""] ??
                "Contact lookup failed"}
            </span>
            {outreach.failure_reason === "contact_key_required" ? (
              <>
                {" "}
                <Link className="underline" href="/settings">
                  Settings
                </Link>
              </>
            ) : (
              outreach.failure_message && (
                <span className="text-muted-foreground">
                  . {outreach.failure_message}
                </span>
              )
            )}
          </p>
          {!editing && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditing(true)}
            >
              Add contact manually
            </Button>
          )}
        </div>
      )}
      {editing && (
        <ManualContactForm
          outreachId={outreach.id}
          onDone={() => setEditing(false)}
        />
      )}
    </div>
  );
}

function ManualContactForm({
  outreachId,
  onDone,
}: {
  outreachId: string;
  onDone: () => void;
}) {
  const setContact = useSetContact();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");

  return (
    <form
      className="mt-3 flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        setContact.mutate(
          {
            outreachId,
            email: email.trim(),
            full_name: name.trim() || undefined,
            title: title.trim() || undefined,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="grid gap-2 sm:grid-cols-3">
        <Input
          aria-label="Contact email"
          type="email"
          required
          placeholder="name@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          aria-label="Contact name"
          placeholder="Full name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Input
          aria-label="Contact title"
          placeholder="Title, e.g. Engineering Manager"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={setContact.isPending}>
          {setContact.isPending ? "Verifying…" : "Verify and use"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <span className="text-muted-foreground text-xs">
          The address is checked with Hunter first (1 verification).
        </span>
      </div>
      {setContact.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(setContact.error)}
        </p>
      )}
    </form>
  );
}
