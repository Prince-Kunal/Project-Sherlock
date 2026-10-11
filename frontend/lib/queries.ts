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
  Match,
  MatchFeed,
  MatchFilters,
  Preferences,
  ResumeOut,
  ResumeVersion,
  HunterKeyStatus,
  Outreach,
  OutreachDetail,
  OutreachList,
  OutreachStatus,
  ReviewStats,
  TailorPreview,
} from "@/lib/types";

export const keys = {
  resume: ["resume"] as const,
  resumeVersion: (v: number) => ["resume", "version", v] as const,
  versions: ["resume", "versions"] as const,
  ats: (v: number | undefined) => ["resume", "ats", v] as const,
  preferences: ["preferences"] as const,
  llmKey: ["settings", "llm-key"] as const,
  hunterKey: ["settings", "hunter-key"] as const,
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

function toQuery(filters: JobFilters | MatchFilters): string {
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

export function useMatches(filters: MatchFilters) {
  return useQuery({
    queryKey: ["matches", filters],
    queryFn: () => apiFetch<MatchFeed>(`/matches?${toQuery(filters)}`),
    placeholderData: (previous) => previous,
  });
}

export type MatchAction = "shortlist" | "hide" | "restore";

export function useMatchAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: MatchAction }) =>
      apiFetch<Match>(`/matches/${id}/${action}`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["matches"] });
      void queryClient.invalidateQueries({ queryKey: ["outreach"] });
    },
  });
}

export function useBlockCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (companyId: string) =>
      apiFetch<unknown>(`/companies/${companyId}/block`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["matches"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useRefreshMatches() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ queued: boolean }>("/matches/refresh", { method: "POST" }),
  });
}

export function useTailorPreview() {
  return useMutation({
    mutationFn: (matchId: string) =>
      apiFetch<TailorPreview>(`/matches/${matchId}/tailor-preview`, {
        method: "POST",
      }),
  });
}

export function useHunterKey() {
  return useQuery({
    queryKey: keys.hunterKey,
    queryFn: () => apiFetch<HunterKeyStatus>("/settings/hunter-key"),
  });
}

export function useSaveHunterKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (apiKey: string) =>
      apiFetch<HunterKeyStatus>("/settings/hunter-key", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    onSuccess: (status) => queryClient.setQueryData(keys.hunterKey, status),
  });
}

export function useDeleteHunterKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>("/settings/hunter-key", { method: "DELETE" }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.hunterKey }),
  });
}

export function useFindContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (matchId: string) =>
      apiFetch<Outreach>(`/matches/${matchId}/find-contact`, {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["matches"] });
      void queryClient.invalidateQueries({ queryKey: keys.hunterKey });
    },
  });
}

export function useSetContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      outreachId,
      ...body
    }: {
      outreachId: string;
      email: string;
      full_name?: string;
      title?: string;
    }) =>
      apiFetch<Outreach>(`/outreach/${outreachId}/contact`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["matches"] });
      void queryClient.invalidateQueries({ queryKey: ["outreach"] });
    },
  });
}

// --- Review queue (Phase 6) ---------------------------------------------------

export function useReviewStats() {
  return useQuery({
    queryKey: ["outreach", "stats"],
    queryFn: () => apiFetch<ReviewStats>("/outreach/stats"),
  });
}

export function useOutreachList(statuses: OutreachStatus[]) {
  const query = statuses.map((s) => `status=${s}`).join("&");
  return useQuery({
    queryKey: ["outreach", "list", statuses],
    queryFn: () => apiFetch<OutreachList>(`/outreach?${query}&limit=100`),
  });
}

export function useOutreachDetail(id: string | null) {
  return useQuery({
    queryKey: ["outreach", "detail", id],
    queryFn: () => apiFetch<OutreachDetail>(`/outreach/${id}`),
    enabled: id !== null,
  });
}

/** Store the returned draft and refresh the lists and stat cards. */
function useOnOutreachChanged() {
  const queryClient = useQueryClient();
  return (detail: OutreachDetail) => {
    queryClient.setQueryData(["outreach", "detail", detail.id], detail);
    void queryClient.invalidateQueries({ queryKey: ["outreach", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["outreach", "stats"] });
    void queryClient.invalidateQueries({ queryKey: ["matches"] });
  };
}

export function useEditDraft() {
  const onChanged = useOnOutreachChanged();
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string;
      subject?: string;
      body?: string;
    }) =>
      apiFetch<OutreachDetail>(`/outreach/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: onChanged,
  });
}

export function useRegenerateDraft() {
  const onChanged = useOnOutreachChanged();
  return useMutation({
    mutationFn: ({ id, hint }: { id: string; hint?: string }) =>
      apiFetch<OutreachDetail>(`/outreach/${id}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ hint: hint || null }),
      }),
    onSuccess: onChanged,
  });
}

export type ReviewAction = "approve" | "skip" | "retry";

export function useReviewAction() {
  const onChanged = useOnOutreachChanged();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: ReviewAction }) =>
      apiFetch<OutreachDetail>(`/outreach/${id}/${action}`, { method: "POST" }),
    onSuccess: onChanged,
  });
}

export function useBuildDrafts() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ queued: boolean }>("/outreach/build", { method: "POST" }),
  });
}

/** "Draft now" on a match: contact → tailor → draft, synchronously. */
export function useDraftNow() {
  const onChanged = useOnOutreachChanged();
  return useMutation({
    mutationFn: (matchId: string) =>
      apiFetch<OutreachDetail>(`/matches/${matchId}/draft`, { method: "POST" }),
    onSuccess: onChanged,
  });
}
