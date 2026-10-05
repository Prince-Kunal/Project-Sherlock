"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type {
  AtsReport,
  Job,
  JobFeed,
  JobFilters,
  LLMKeyStatus,
  MasterResume,
  Preferences,
  ResumeOut,
  ResumeVersion,
} from "@/lib/types";

export const keys = {
  resume: ["resume"] as const,
  resumeVersion: (v: number) => ["resume", "version", v] as const,
  versions: ["resume", "versions"] as const,
  ats: (v: number | undefined) => ["resume", "ats", v] as const,
  preferences: ["preferences"] as const,
  llmKey: ["settings", "llm-key"] as const,
};

/** Current resume, or null when the user hasn't uploaded one yet. */
export function useResume() {
  return useQuery({
    queryKey: keys.resume,
    queryFn: async () => {
      try {
        return await apiFetch<ResumeOut>("/resume");
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export function useResumeVersion(version: number | null) {
  return useQuery({
    queryKey: keys.resumeVersion(version ?? 0),
    queryFn: () => apiFetch<ResumeOut>(`/resume/versions/${version}`),
    enabled: version !== null,
  });
}

export function useResumeVersions(enabled: boolean) {
  return useQuery({
    queryKey: keys.versions,
    queryFn: () => apiFetch<ResumeVersion[]>("/resume/versions"),
    enabled,
  });
}

export function useAtsCheck(version: number | undefined) {
  return useQuery({
    queryKey: keys.ats(version),
    queryFn: () => apiFetch<AtsReport>(`/resume/ats-check?version=${version}`),
    enabled: version !== undefined,
    staleTime: Infinity, // a given version never changes
  });
}

function useInvalidateResume() {
  const queryClient = useQueryClient();
  return (saved: ResumeOut) => {
    queryClient.setQueryData(keys.resume, saved);
    void queryClient.invalidateQueries({ queryKey: keys.versions });
  };
}

export function useUploadResume() {
  const onSaved = useInvalidateResume();
  return useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return apiFetch<ResumeOut>("/resume/upload", { method: "POST", body });
    },
    onSuccess: onSaved,
  });
}

export function useSaveResume() {
  const onSaved = useInvalidateResume();
  return useMutation({
    mutationFn: (resume: MasterResume) =>
      apiFetch<ResumeOut>("/resume", {
        method: "PUT",
        body: JSON.stringify(resume),
      }),
    onSuccess: onSaved,
  });
}

export function useTagSkills() {
  return useMutation({
    mutationFn: (texts: string[]) =>
      apiFetch<{ index: number; skills: string[] }[]>("/resume/tag-skills", {
        method: "POST",
        body: JSON.stringify({ texts }),
      }),
  });
}

export function usePreferences() {
  return useQuery({
    queryKey: keys.preferences,
    queryFn: () => apiFetch<Preferences>("/preferences"),
  });
}

export function useSavePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (prefs: Preferences) =>
      apiFetch<Preferences>("/preferences", {
        method: "PUT",
        body: JSON.stringify(prefs),
      }),
    onSuccess: (saved) => queryClient.setQueryData(keys.preferences, saved),
  });
}

export function useLlmKey() {
  return useQuery({
    queryKey: keys.llmKey,
    queryFn: () => apiFetch<LLMKeyStatus>("/settings/llm-key"),
  });
}

export function useSaveLlmKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (apiKey: string) =>
      apiFetch<LLMKeyStatus>("/settings/llm-key", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    onSuccess: (status) => queryClient.setQueryData(keys.llmKey, status),
  });
}

export function useDeleteLlmKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/settings/llm-key", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.llmKey }),
  });
}

function toQuery(filters: JobFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

export function useJobs(filters: JobFilters) {
  return useQuery({
    queryKey: ["jobs", filters],
    queryFn: () => apiFetch<JobFeed>(`/jobs?${toQuery(filters)}`),
    placeholderData: (previous) => previous,
  });
}

export function useAddJobUrl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) =>
      apiFetch<Job>("/jobs/manual", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export function usePollNow() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ job_id: string | null }>("/admin/poll", { method: "POST" }),
  });
}
