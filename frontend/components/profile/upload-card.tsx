"use client";

import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { useUploadResume } from "@/lib/queries";

const MAX_BYTES = 5 * 1024 * 1024;

export function UploadCard({
  hasResume,
  disabled,
}: {
  hasResume: boolean;
  disabled: boolean;
}) {
  const upload = useUploadResume();
  const input = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const onFile = (file: File | undefined) => {
    setLocalError(null);
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      setLocalError("Upload a PDF or DOCX file.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setLocalError("The file must be 5 MB or smaller.");
      return;
    }
    upload.mutate(file);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {hasResume ? "Upload a new resume" : "Upload your resume"}
        </CardTitle>
        <CardDescription>
          PDF or Word (.docx), up to 5 MB. Sherlock reads it into an editable
          master resume. Your email and phone number are kept out of what is
          sent to Gemini.{" "}
          {hasResume && "Uploading creates a new version; older ones are kept."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="hidden"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          className="self-start"
          disabled={disabled || upload.isPending}
          onClick={() => input.current?.click()}
        >
          <Upload /> {upload.isPending ? "Reading your resume…" : "Choose file"}
        </Button>
        {upload.isPending && (
          <p className="text-muted-foreground text-sm">
            This takes 10–30 seconds on the Gemini free tier.
          </p>
        )}
        {(localError || upload.isError) && (
          <p className="text-destructive text-sm">
            {localError ?? errorMessage(upload.error)}
          </p>
        )}
        {upload.isSuccess && (
          <p className="text-sm">
            Parsed into version {upload.data.version}. Review every section
            below: the AI can misread layouts.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
