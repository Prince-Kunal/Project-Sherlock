"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { EasterEggs } from "@/components/easter-eggs";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <EasterEggs />
      <Toaster
        position="bottom-right"
        toastOptions={{
          classNames: {
            toast:
              "!rounded-2xl !border-border !bg-popover !text-popover-foreground shadow-lift !font-sans",
            title: "!font-medium",
            description: "!text-muted-foreground",
          },
        }}
      />
    </QueryClientProvider>
  );
}
