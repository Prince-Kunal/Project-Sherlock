import { EmptyPage } from "@/components/empty-page";
import { LlmKeyCard } from "@/components/settings/llm-key-card";

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <LlmKeyCard />
      <EmptyPage
        title="More settings"
        phase={9}
        description="Pause switch, Gmail connection and data deletion will live here."
      />
    </div>
  );
}
