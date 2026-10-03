import { EmptyPage } from "@/components/empty-page";

export default function JobsPage() {
  return (
    <EmptyPage
      title="Jobs feed"
      phase={2}
      description="Fresh openings (14 days or newer) from Greenhouse, Lever, Ashby, Adzuna and HN will appear here."
    />
  );
}
