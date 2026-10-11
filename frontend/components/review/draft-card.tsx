"use client";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ExternalLink,
  FileText,
  Pencil,
  RefreshCw,
  SkipForward,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import {
  ManualContactForm,
  ROLE_LABELS,
} from "@/components/jobs/contact-panel";
import { ResumeChanges } from "@/components/review/resume-changes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api";
import { age, SOURCE_LABELS, TYPE_LABELS } from "@/lib/jobs";
import {
  useEditDraft,
  useRegenerateDraft,
  useReviewAction,
} from "@/lib/queries";
import type { OutreachDetail } from "@/lib/types";

export function scoreClass(score: number | null): string {
  if (score === null) return "bg-muted text-muted-foreground";
  if (score >= 85)
    return "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-950";
  if (score >= 70) return "bg-primary text-primary-foreground";
  if (score >= 50) return "bg-amber-500 text-amber-950";
  return "bg-muted text-muted-foreground";
}

/** One draft in review: job, contact, email (editable), tailored resume, and the actions. */
export function DraftCard({
  draft,
  onDone,
}: {
  draft: OutreachDetail;
  onDone: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const action = useReviewAction();
  const inReview = draft.status === "pending_review";
  const busy = action.isPending;

  return (
    <article className="bg-card flex flex-col gap-4 rounded-xl border p-4">
      <JobHeader draft={draft} />
      <ContactBlock draft={draft} editable={inReview} />

      {editing ? (
        <EmailEditor draft={draft} onClose={() => setEditing(false)} />
      ) : (
        <EmailView draft={draft} />
      )}

      <AttachmentRow draft={draft} />

      {inReview && !editing && (
        <div className="flex flex-col gap-2 border-t pt-3">
          {regenerating ? (
            <RegenerateForm
              draftId={draft.id}
              onClose={() => setRegenerating(false)}
            />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                disabled={busy}
                onClick={() =>
                  action.mutate(
                    { id: draft.id, action: "approve" },
                    { onSuccess: onDone },
                  )
                }
                title="Approve (a)"
              >
                <Check /> Approve and send
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setEditing(true)}
              >
                <Pencil /> Edit
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setRegenerating(true)}
              >
                <RefreshCw /> Regenerate
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  action.mutate(
                    { id: draft.id, action: "skip" },
                    { onSuccess: onDone },
                  )
                }
                title="Skip (s)"
              >
                <SkipForward /> Skip
              </Button>
              <span className="text-muted-foreground ml-auto hidden text-xs sm:inline">
                <kbd>a</kbd> approve · <kbd>s</kbd> skip · <kbd>j</kbd>/
                <kbd>k</kbd> next/previous
              </span>
            </div>
          )}
          {action.isError && (
            <p className="text-destructive text-sm">
              {errorMessage(action.error)}
            </p>
          )}
        </div>
      )}
      {draft.status === "approved" && (
        <p className="flex items-center gap-1.5 border-t pt-3 text-sm text-emerald-700 dark:text-emerald-400">
          <CheckCircle2 className="size-4" /> Approved. It will be sent in your
          send window once Gmail sending is set up (Phase 7).
        </p>
      )}
    </article>
  );
}

function JobHeader({ draft }: { draft: OutreachDetail }) {
  const job = draft.job;
  return (
    <header className="flex gap-3">
      <div
        className={`flex size-11 shrink-0 items-center justify-center rounded-lg text-base font-semibold tabular-nums ${scoreClass(draft.fit_score)}`}
        title="Fit score out of 100"
      >
        {draft.fit_score ?? "–"}
      </div>
      <div className="min-w-0 flex-1">
        {job?.url ? (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-start gap-1 font-medium hover:underline"
          >
            {job.title}
            <ExternalLink className="text-muted-foreground mt-1 size-3 shrink-0" />
          </a>
        ) : (
          <span className="font-medium">
            {draft.job_title ?? draft.company.name}
          </span>
        )}
        <p className="text-muted-foreground text-sm">
          {draft.company.name}
          {job && (
            <>
              {" "}
              · {job.location ?? "Location not stated"}
              {job.remote && " · Remote"} · {age(job.age_days)}
              {job.employment_type && ` · ${TYPE_LABELS[job.employment_type]}`}
              {" · "}
              {SOURCE_LABELS[job.source] ?? job.source}
            </>
          )}
        </p>
        {(draft.matched_skills.length > 0 ||
          draft.missing_skills.length > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {draft.matched_skills.map((s) => (
              <Badge key={`m-${s}`} variant="secondary">
                {s}
              </Badge>
            ))}
            {draft.missing_skills.length > 0 && (
              <span className="text-muted-foreground ml-1 text-xs">
                Missing:
              </span>
            )}
            {draft.missing_skills.map((s) => (
              <Badge
                key={`x-${s}`}
                variant="outline"
                className="text-muted-foreground border-dashed"
              >
                {s}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </header>
  );
}

function ContactBlock({
  draft,
  editable,
}: {
  draft: OutreachDetail;
  editable: boolean;
}) {
  const [changing, setChanging] = useState(false);
  const contact = draft.contact;
  if (!contact) return null;

  return (
    <section className="bg-muted/30 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-muted-foreground text-xs">To</p>
          <p className="font-medium">
            {contact.full_name}
            <span className="text-muted-foreground font-normal">
              {" "}
              · {contact.title ?? ROLE_LABELS[contact.role_category]}
            </span>
          </p>
          <p className="flex flex-wrap items-center gap-1.5">
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
        {editable && !changing && (
          <Button variant="ghost" size="sm" onClick={() => setChanging(true)}>
            Change contact
          </Button>
        )}
      </div>
      {changing && (
        <ManualContactForm
          outreachId={draft.id}
          onDone={() => setChanging(false)}
        />
      )}
    </section>
  );
}

function EmailView({ draft }: { draft: OutreachDetail }) {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <p className="text-muted-foreground text-xs">Subject</p>
        <p className="font-medium">{draft.subject}</p>
      </div>
      <div className="bg-background rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">
        {draft.body}
      </div>
      {draft.personalization_source && (
        <p className="text-muted-foreground text-xs">
          Hook based on: “{draft.personalization_source}”
        </p>
      )}
    </section>
  );
}

function EmailEditor({
  draft,
  onClose,
}: {
  draft: OutreachDetail;
  onClose: () => void;
}) {
  const edit = useEditDraft();
  const [subject, setSubject] = useState(draft.subject ?? "");
  const [body, setBody] = useState(draft.body ?? "");

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        edit.mutate({ id: draft.id, subject, body }, { onSuccess: onClose });
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground text-xs">Subject</span>
        <Input
          value={subject}
          maxLength={200}
          onChange={(e) => setSubject(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground text-xs">Email</span>
        <Textarea
          value={body}
          rows={14}
          className="leading-relaxed"
          onChange={(e) => setBody(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={edit.isPending}>
          {edit.isPending ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <span className="text-muted-foreground text-xs">
          Keep the opt-out line; it goes in every email.
        </span>
      </div>
      {edit.isError && (
        <p className="text-destructive text-sm">{errorMessage(edit.error)}</p>
      )}
    </form>
  );
}

function RegenerateForm({
  draftId,
  onClose,
}: {
  draftId: string;
  onClose: () => void;
}) {
  const regenerate = useRegenerateDraft();
  const [hint, setHint] = useState("");

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        regenerate.mutate(
          { id: draftId, hint: hint.trim() || undefined },
          { onSuccess: onClose },
        );
      }}
    >
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          autoFocus
          aria-label="What to change"
          placeholder="Optional: what should change? e.g. mention I can start in May"
          value={hint}
          maxLength={300}
          onChange={(e) => setHint(e.target.value)}
        />
        <div className="flex gap-2">
          <Button type="submit" disabled={regenerate.isPending}>
            <RefreshCw className={regenerate.isPending ? "animate-spin" : ""} />
            {regenerate.isPending ? "Writing…" : "Regenerate"}
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        Writes a new email (one Gemini request). The tailored resume stays the
        same.
      </p>
      {regenerate.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(regenerate.error)}
        </p>
      )}
    </form>
  );
}

function AttachmentRow({ draft }: { draft: OutreachDetail }) {
  const [showDiff, setShowDiff] = useState(false);
  const [showPdf, setShowPdf] = useState(false);
  const coverage = draft.keyword_coverage;
  const total = coverage
    ? coverage.matched.length + coverage.missing.length
    : 0;
  if (!draft.resume_pdf_url) return null;
  const pdfSrc = `/api${draft.resume_pdf_url}`;

  return (
    <section className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <a
          href={pdfSrc}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 font-medium underline-offset-4 hover:underline"
        >
          <FileText className="size-4" />
          {draft.resume_filename ?? "Resume.pdf"}
        </a>
        {draft.ats && (
          <span className="inline-flex items-center gap-1.5">
            {draft.ats.passed ? (
              <CheckCircle2 className="size-4 text-emerald-600" />
            ) : (
              <XCircle className="text-destructive size-4" />
            )}
            ATS check {draft.ats.passed ? "passed" : "failed"}
          </span>
        )}
        {coverage && total > 0 && (
          <span>
            ATS match: {coverage.matched.length}/{total} must-haves
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={showDiff}
          onClick={() => setShowDiff((s) => !s)}
        >
          {showDiff ? "Hide diff" : `View diff (${draft.resume_diff.length})`}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={showPdf}
          onClick={() => setShowPdf((s) => !s)}
        >
          {showPdf ? "Hide PDF" : "Preview PDF"}
        </Button>
      </div>
      {coverage && coverage.missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">
            Not on your resume (genuine gaps, never added):
          </span>
          {coverage.missing.map((k) => (
            <Badge
              key={k}
              variant="outline"
              className="text-muted-foreground border-dashed"
            >
              {k}
            </Badge>
          ))}
        </div>
      )}
      {showDiff && <ResumeChanges changes={draft.resume_diff} />}
      {showPdf && (
        <iframe
          title="Tailored resume"
          src={pdfSrc}
          className="h-[70vh] w-full rounded-md border bg-white"
        />
      )}
    </section>
  );
}
