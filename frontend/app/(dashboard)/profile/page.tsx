"use client";

import Link from "next/link";
import { useState } from "react";

import { PreferencesForm } from "@/components/profile/preferences-form";
import { PreviewPanel } from "@/components/profile/preview-panel";
import { ResumeEditor } from "@/components/profile/resume-editor";
import { UploadCard } from "@/components/profile/upload-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api";
import { useLlmKey, useResume } from "@/lib/queries";

export default function ProfilePage() {
  const llmKey = useLlmKey();
  const resume = useResume();
  const [tab, setTab] = useState("resume");

  const keyMissing =
    llmKey.data !== undefined &&
    !llmKey.data.configured &&
    !llmKey.data.owner_fallback_allowed;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        Profile and resume
      </h1>

      {keyMissing && (
        <Alert variant="destructive">
          <AlertTitle>Add your Gemini API key first</AlertTitle>
          <AlertDescription>
            Reading your resume needs your own free Gemini key.{" "}
            <Link href="/settings" className="underline">
              Add it in Settings
            </Link>
            .
          </AlertDescription>
        </Alert>
      )}

      <UploadCard hasResume={!!resume.data} disabled={keyMissing} />

      {resume.isError && (
        <p className="text-destructive text-sm">{errorMessage(resume.error)}</p>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="resume" disabled={!resume.data}>
            Master resume
          </TabsTrigger>
          <TabsTrigger value="preview" disabled={!resume.data}>
            Preview and ATS check
          </TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
        </TabsList>
        <TabsContent value="resume" className="pt-4">
          {resume.data ? (
            <ResumeEditor current={resume.data} />
          ) : (
            resume.isSuccess && (
              <p className="text-muted-foreground text-sm">
                Upload a resume to start. You can then edit every section here.
              </p>
            )
          )}
        </TabsContent>
        <TabsContent value="preview" className="pt-4">
          {resume.data && <PreviewPanel version={resume.data.version} />}
        </TabsContent>
        <TabsContent value="preferences" className="pt-4">
          <PreferencesForm />
        </TabsContent>
      </Tabs>
    </div>
  );
}
