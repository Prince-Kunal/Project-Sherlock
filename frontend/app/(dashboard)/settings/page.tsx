import { PageHeader } from "@/components/page-header";
import { ApolloKeyCard } from "@/components/settings/apollo-key-card";
import { DeleteAccountCard } from "@/components/settings/delete-account-card";
import { DraftMixCard } from "@/components/settings/draft-mix-card";
import { HunterKeyCard } from "@/components/settings/hunter-key-card";
import { LlmKeyCard } from "@/components/settings/llm-key-card";
import { ScheduleCard } from "@/components/settings/schedule-card";
import { SendingCard } from "@/components/settings/sending-card";
import { UsageCard } from "@/components/settings/usage-card";

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Sending, the schedule, and the keys Sherlock works with. Keys are stored encrypted and never shown again."
      />
      <SendingCard />
      <ScheduleCard />
      <DraftMixCard />
      <UsageCard />
      <LlmKeyCard />
      <HunterKeyCard />
      <ApolloKeyCard />
      <DeleteAccountCard />
    </div>
  );
}
