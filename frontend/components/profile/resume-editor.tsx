"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ChipsInput } from "@/components/chips-input";
import { BulletsEditor } from "@/components/profile/bullets-editor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api";
import {
  useResumeVersion,
  useResumeVersions,
  useSaveResume,
} from "@/lib/queries";
import type {
  Education,
  Experience,
  MasterResume,
  Project,
  ResumeOut,
} from "@/lib/types";

const DATE_HINT = "YYYY-MM, YYYY or present";

function Field({
  label,
  value,
  onChange,
  placeholder,
  className,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <Label
      className={`flex flex-col items-stretch gap-1 font-normal ${className ?? ""}`}
    >
      <span className="text-muted-foreground text-xs">{label}</span>
      <Input
        value={value ?? ""}
        placeholder={placeholder}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : e.target.value)
        }
      />
    </Label>
  );
}

function Section({
  title,
  description,
  onAdd,
  readOnly,
  children,
}: {
  title: string;
  description?: string;
  onAdd?: () => void;
  readOnly: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {onAdd && !readOnly && (
          <CardAction>
            <Button type="button" variant="outline" size="sm" onClick={onAdd}>
              <Plus /> Add
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

function EntryShell({
  label,
  onRemove,
  readOnly,
  children,
}: {
  label: string;
  onRemove: () => void;
  readOnly: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        {!readOnly && (
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            <Trash2 /> Remove
          </Button>
        )}
      </div>
      {children}
    </div>
  );
}

const emptyEducation = (): Education => ({
  id: "",
  institution: "",
  degree: null,
  field: null,
  location: null,
  start: null,
  end: null,
  gpa: null,
  bullets: [],
});
const emptyExperience = (): Experience => ({
  id: "",
  org: "",
  role: "",
  location: null,
  start: null,
  end: null,
  bullets: [],
});
const emptyProject = (): Project => ({
  id: "",
  name: "",
  link: null,
  tech: [],
  start: null,
  end: null,
  bullets: [],
});

function ResumeForm({
  initial,
  readOnly,
  onSave,
  saving,
  saveLabel,
}: {
  initial: MasterResume;
  readOnly: boolean;
  onSave: (resume: MasterResume) => void;
  saving: boolean;
  saveLabel: string;
}) {
  const [draft, setDraft] = useState<MasterResume>(initial);
  const [dirty, setDirty] = useState(false);

  const update = (fn: (d: MasterResume) => void) => {
    setDraft((current) => {
      const next = structuredClone(current);
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const skillEntries = Object.entries(draft.skills);

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(draft);
      }}
    >
      <fieldset disabled={readOnly} className="contents">
        <Section title="Contact" readOnly={readOnly}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Name"
              value={draft.basics.name}
              onChange={(v) => update((d) => void (d.basics.name = v ?? ""))}
            />
            <Field
              label="Location"
              placeholder="City, Country"
              value={draft.basics.location}
              onChange={(v) => update((d) => void (d.basics.location = v))}
            />
            <Field
              label="Email"
              value={draft.basics.email}
              onChange={(v) => update((d) => void (d.basics.email = v))}
            />
            <Field
              label="Phone"
              value={draft.basics.phone}
              onChange={(v) => update((d) => void (d.basics.phone = v))}
            />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-muted-foreground text-xs">
              Links (printed as visible text, e.g. github.com/you)
            </span>
            {draft.basics.links.map((link, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  aria-label="Link label"
                  className="w-32"
                  value={link.label}
                  onChange={(e) =>
                    update(
                      (d) => void (d.basics.links[i].label = e.target.value),
                    )
                  }
                />
                <Input
                  aria-label="Link URL"
                  value={link.url}
                  onChange={(e) =>
                    update((d) => void (d.basics.links[i].url = e.target.value))
                  }
                />
                {!readOnly && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    title="Remove link"
                    onClick={() =>
                      update((d) => void d.basics.links.splice(i, 1))
                    }
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
            ))}
            {!readOnly && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() =>
                  update(
                    (d) => void d.basics.links.push({ label: "", url: "" }),
                  )
                }
              >
                <Plus /> Add link
              </Button>
            )}
          </div>
          <Label className="flex flex-col items-stretch gap-1 font-normal">
            <span className="text-muted-foreground text-xs">
              Summary (optional)
            </span>
            <Textarea
              rows={3}
              value={draft.summary ?? ""}
              onChange={(e) =>
                update((d) => void (d.summary = e.target.value || null))
              }
            />
          </Label>
        </Section>

        <Section
          title="Education"
          readOnly={readOnly}
          onAdd={() => update((d) => void d.education.push(emptyEducation()))}
        >
          {draft.education.map((e, i) => (
            <EntryShell
              key={e.id || `edu-new-${i}`}
              label={e.id || "New entry"}
              readOnly={readOnly}
              onRemove={() => update((d) => void d.education.splice(i, 1))}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label="Institution"
                  value={e.institution}
                  onChange={(v) =>
                    update((d) => void (d.education[i].institution = v ?? ""))
                  }
                />
                <Field
                  label="Degree"
                  placeholder="B.Tech"
                  value={e.degree}
                  onChange={(v) =>
                    update((d) => void (d.education[i].degree = v))
                  }
                />
                <Field
                  label="Field"
                  placeholder="Computer Science"
                  value={e.field}
                  onChange={(v) =>
                    update((d) => void (d.education[i].field = v))
                  }
                />
                <Field
                  label="GPA"
                  value={e.gpa}
                  onChange={(v) => update((d) => void (d.education[i].gpa = v))}
                />
                <Field
                  label="Location"
                  value={e.location}
                  onChange={(v) =>
                    update((d) => void (d.education[i].location = v))
                  }
                />
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Start"
                    placeholder={DATE_HINT}
                    value={e.start}
                    onChange={(v) =>
                      update((d) => void (d.education[i].start = v))
                    }
                  />
                  <Field
                    label="End"
                    placeholder={DATE_HINT}
                    value={e.end}
                    onChange={(v) =>
                      update((d) => void (d.education[i].end = v))
                    }
                  />
                </div>
              </div>
              <BulletsEditor
                idPrefix={`edu${i}`}
                readOnly={readOnly}
                bullets={e.bullets}
                onChange={(b) =>
                  update((d) => void (d.education[i].bullets = b))
                }
              />
            </EntryShell>
          ))}
        </Section>

        <Section
          title="Experience"
          readOnly={readOnly}
          onAdd={() => update((d) => void d.experience.push(emptyExperience()))}
        >
          {draft.experience.map((e, i) => (
            <EntryShell
              key={e.id || `exp-new-${i}`}
              label={e.id || "New entry"}
              readOnly={readOnly}
              onRemove={() => update((d) => void d.experience.splice(i, 1))}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label="Role"
                  value={e.role}
                  onChange={(v) =>
                    update((d) => void (d.experience[i].role = v ?? ""))
                  }
                />
                <Field
                  label="Organisation"
                  value={e.org}
                  onChange={(v) =>
                    update((d) => void (d.experience[i].org = v ?? ""))
                  }
                />
                <Field
                  label="Location"
                  value={e.location}
                  onChange={(v) =>
                    update((d) => void (d.experience[i].location = v))
                  }
                />
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Start"
                    placeholder={DATE_HINT}
                    value={e.start}
                    onChange={(v) =>
                      update((d) => void (d.experience[i].start = v))
                    }
                  />
                  <Field
                    label="End"
                    placeholder={DATE_HINT}
                    value={e.end}
                    onChange={(v) =>
                      update((d) => void (d.experience[i].end = v))
                    }
                  />
                </div>
              </div>
              <BulletsEditor
                idPrefix={`exp${i}`}
                readOnly={readOnly}
                bullets={e.bullets}
                onChange={(b) =>
                  update((d) => void (d.experience[i].bullets = b))
                }
              />
            </EntryShell>
          ))}
        </Section>

        <Section
          title="Projects"
          readOnly={readOnly}
          onAdd={() => update((d) => void d.projects.push(emptyProject()))}
        >
          {draft.projects.map((p, i) => (
            <EntryShell
              key={p.id || `proj-new-${i}`}
              label={p.id || "New entry"}
              readOnly={readOnly}
              onRemove={() => update((d) => void d.projects.splice(i, 1))}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label="Name"
                  value={p.name}
                  onChange={(v) =>
                    update((d) => void (d.projects[i].name = v ?? ""))
                  }
                />
                <Field
                  label="Link"
                  placeholder="github.com/you/project"
                  value={p.link}
                  onChange={(v) => update((d) => void (d.projects[i].link = v))}
                />
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">Tech</span>
                  <ChipsInput
                    ariaLabel="Project tech"
                    value={p.tech}
                    onChange={(tech) =>
                      update((d) => void (d.projects[i].tech = tech))
                    }
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Start"
                    placeholder={DATE_HINT}
                    value={p.start}
                    onChange={(v) =>
                      update((d) => void (d.projects[i].start = v))
                    }
                  />
                  <Field
                    label="End"
                    placeholder={DATE_HINT}
                    value={p.end}
                    onChange={(v) =>
                      update((d) => void (d.projects[i].end = v))
                    }
                  />
                </div>
              </div>
              <BulletsEditor
                idPrefix={`proj${i}`}
                readOnly={readOnly}
                bullets={p.bullets}
                onChange={(b) =>
                  update((d) => void (d.projects[i].bullets = b))
                }
              />
            </EntryShell>
          ))}
        </Section>

        <Section
          title="Skills"
          description="One line per category, printed as a plain comma-separated list."
          readOnly={readOnly}
          onAdd={() =>
            update(
              (d) =>
                void (d.skills[`Category ${Object.keys(d.skills).length + 1}`] =
                  []),
            )
          }
        >
          {skillEntries.map(([category, items], i) => (
            <div
              key={i}
              className="flex flex-col gap-2 sm:flex-row sm:items-start"
            >
              <Input
                aria-label="Skill category"
                className="sm:w-44"
                value={category}
                onChange={(e) =>
                  update((d) => {
                    // Rename while keeping category order.
                    d.skills = Object.fromEntries(
                      Object.entries(d.skills).map(([k, v], j) => [
                        j === i ? e.target.value : k,
                        v,
                      ]),
                    );
                  })
                }
              />
              <div className="flex-1">
                <ChipsInput
                  ariaLabel={`${category} skills`}
                  value={items}
                  onChange={(next) =>
                    update((d) => void (d.skills[category] = next))
                  }
                />
              </div>
              {!readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  title="Remove category"
                  onClick={() => update((d) => void delete d.skills[category])}
                >
                  <Trash2 />
                </Button>
              )}
            </div>
          ))}
        </Section>

        <Section
          title="Achievements"
          description="Awards, certifications, publications, leadership."
          readOnly={readOnly}
        >
          <BulletsEditor
            idPrefix="ach"
            readOnly={readOnly}
            bullets={draft.achievements}
            onChange={(b) => update((d) => void (d.achievements = b))}
          />
        </Section>
      </fieldset>

      <div className="bg-background/95 sticky bottom-0 flex items-center justify-end gap-3 border-t py-3 backdrop-blur">
        {dirty && !readOnly && (
          <span className="text-muted-foreground text-sm">Unsaved changes</span>
        )}
        <Button type="submit" disabled={saving || (!readOnly && !dirty)}>
          {saving ? "Saving…" : saveLabel}
        </Button>
      </div>
    </form>
  );
}

export function ResumeEditor({ current }: { current: ResumeOut }) {
  const save = useSaveResume();
  const versions = useResumeVersions(true);
  const [viewing, setViewing] = useState<number | null>(null);
  const older = useResumeVersion(viewing);
  const showingOld = viewing !== null && viewing !== current.version;
  const shown = showingOld ? older.data : current;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Version</span>
        <select
          aria-label="Resume version"
          className="border-input h-8 rounded-lg border bg-transparent px-2"
          value={viewing ?? current.version}
          onChange={(e) => setViewing(Number(e.target.value))}
        >
          {(
            versions.data ?? [
              { version: current.version, is_current: true, created_at: "" },
            ]
          ).map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
              {v.is_current ? " (current)" : ""}
              {v.created_at
                ? ` · ${new Date(v.created_at).toLocaleString()}`
                : ""}
            </option>
          ))}
        </select>
        {showingOld && (
          <Badge variant="secondary">Read-only: older version</Badge>
        )}
      </div>
      {save.isError && (
        <p className="text-destructive text-sm">{errorMessage(save.error)}</p>
      )}
      {shown && (
        <ResumeForm
          // Remount on version change so the draft resets to the saved data.
          key={`${showingOld ? "old" : "cur"}-${shown.version}`}
          initial={shown.data}
          readOnly={showingOld}
          saving={save.isPending}
          saveLabel={
            showingOld
              ? `Restore v${shown.version} as a new version`
              : "Save as new version"
          }
          onSave={(resume) =>
            save.mutate(resume, { onSuccess: () => setViewing(null) })
          }
        />
      )}
    </div>
  );
}
