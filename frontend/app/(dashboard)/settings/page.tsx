import { AllowedPeopleCard } from "@/components/settings/allowed-people-card";
import { HunterKeyCard } from "@/components/settings/hunter-key-card";
import { LlmKeyCard } from "@/components/settings/llm-key-card";
import { SendingCard } from "@/components/settings/sending-card";

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <SendingCard />
      <LlmKeyCard />
      <HunterKeyCard />
      <AllowedPeopleCard />
    </div>
  );
}
