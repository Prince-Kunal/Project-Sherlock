import { PageHeader } from "@/components/page-header";
import { AllowedPeopleCard } from "@/components/settings/allowed-people-card";
import { ApolloKeyCard } from "@/components/settings/apollo-key-card";
import { DraftMixCard } from "@/components/settings/draft-mix-card";
import { HunterKeyCard } from "@/components/settings/hunter-key-card";
import { LlmKeyCard } from "@/components/settings/llm-key-card";
import { SendingCard } from "@/components/settings/sending-card";

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Sending, the draft mix, and the keys Sherlock works with. Keys are stored encrypted and never shown again."
      />
      <SendingCard />
      <DraftMixCard />
      <LlmKeyCard />
      <HunterKeyCard />
      <ApolloKeyCard />
      <AllowedPeopleCard />
    </div>
  );
}
