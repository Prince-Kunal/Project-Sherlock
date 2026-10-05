"use client";

import { ArrowDown, ArrowUp, Plus, Sparkles, Trash2 } from "lucide-react";

import { ChipsInput } from "@/components/chips-input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api";
import { useTagSkills } from "@/lib/queries";
import type { Bullet } from "@/lib/types";

export const newBullet = (): Bullet => ({
  id: "",
  text: "",
  skills: [],
  pinned: false,
});

function move<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function BulletsEditor({
  bullets,
  onChange,
  readOnly,
  idPrefix,
}: {
  bullets: Bullet[];
  onChange: (next: Bullet[]) => void;
  readOnly: boolean;
  idPrefix: string;
}) {
  const tag = useTagSkills();
  const set = (index: number, patch: Partial<Bullet>) =>
    onChange(bullets.map((b, i) => (i === index ? { ...b, ...patch } : b)));

  return (
    <div className="flex flex-col gap-3">
      {bullets.map((bullet, index) => {
        const key = bullet.id || `${idPrefix}-new-${index}`;
        return (
          <fieldset
            key={key}
            disabled={readOnly}
            className="bg-muted/30 flex flex-col gap-2 rounded-lg border p-3"
          >
            <div className="flex items-start gap-2">
              <span className="text-muted-foreground mt-1.5 w-16 shrink-0 font-mono text-xs">
                {bullet.id || "new"}
              </span>
              <Textarea
                aria-label="Bullet text"
                value={bullet.text}
                rows={2}
                onChange={(e) => set(index, { text: e.target.value })}
              />
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex-1">
                <ChipsInput
                  ariaLabel="Skills shown by this bullet"
                  lowercase
                  placeholder="Skills this bullet shows (Enter to add)"
                  value={bullet.skills}
                  onChange={(skills) => set(index, { skills })}
                />
              </div>
              {!readOnly && (
                <div className="flex items-center gap-1">
                  <Label className="mr-2 flex items-center gap-2 text-xs font-normal">
                    <Switch
                      checked={bullet.pinned}
                      onCheckedChange={(pinned) => set(index, { pinned })}
                    />
                    Pinned
                  </Label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    title="Suggest skills (uses 1 Gemini request)"
                    disabled={!bullet.text.trim() || tag.isPending}
                    onClick={() =>
                      tag.mutate([bullet.text], {
                        onSuccess: ([result]) =>
                          set(index, {
                            skills: Array.from(
                              new Set([...bullet.skills, ...result.skills]),
                            ),
                          }),
                      })
                    }
                  >
                    <Sparkles />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    title="Move up"
                    disabled={index === 0}
                    onClick={() => onChange(move(bullets, index, index - 1))}
                  >
                    <ArrowUp />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    title="Move down"
                    disabled={index === bullets.length - 1}
                    onClick={() => onChange(move(bullets, index, index + 1))}
                  >
                    <ArrowDown />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    title="Delete bullet"
                    onClick={() =>
                      onChange(bullets.filter((_, i) => i !== index))
                    }
                  >
                    <Trash2 />
                  </Button>
                </div>
              )}
            </div>
          </fieldset>
        );
      })}
      {tag.isError && (
        <p className="text-destructive text-sm">{errorMessage(tag.error)}</p>
      )}
      {!readOnly && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => onChange([...bullets, newBullet()])}
        >
          <Plus /> Add bullet
        </Button>
      )}
    </div>
  );
}
