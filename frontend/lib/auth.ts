"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch, type Session, type User } from "@/lib/api";

const ME_KEY = ["auth", "me"] as const;

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => apiFetch<User>("/auth/me"),
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 2,
  });
}

export function useDevLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<Session>("/auth/dev-login", { method: "POST" }),
    onSuccess: (session) => queryClient.setQueryData(ME_KEY, session.user),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => queryClient.clear(),
  });
}
