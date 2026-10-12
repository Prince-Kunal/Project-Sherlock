"use client";

import { useState } from "react";

import { CompaniesPanel } from "@/components/admin/companies-panel";
import { SuppressionPanel } from "@/components/admin/suppression-panel";
import { UsagePanel } from "@/components/admin/usage-panel";
import { PageHeader } from "@/components/page-header";
import { AllowedPeopleCard } from "@/components/settings/allowed-people-card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "@/lib/auth";

export default function AdminPage() {
  const me = useMe();
  const [tab, setTab] = useState("usage");

  if (!me.data?.is_admin) {
    return (
      <PageHeader
        title="Admin"
        description="Only the owner can see this page."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Admin"
        description="Who can sign in, what everyone uses, the companies Sherlock watches, and who must never be emailed."
      />
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="usage">Usage</TabsTrigger>
          <TabsTrigger value="people">People</TabsTrigger>
          <TabsTrigger value="companies">Companies</TabsTrigger>
          <TabsTrigger value="suppression">Do not contact</TabsTrigger>
        </TabsList>
        <TabsContent value="usage" className="pt-4">
          <UsagePanel />
        </TabsContent>
        <TabsContent value="people" className="pt-4">
          <AllowedPeopleCard />
        </TabsContent>
        <TabsContent value="companies" className="pt-4">
          <CompaniesPanel />
        </TabsContent>
        <TabsContent value="suppression" className="pt-4">
          <SuppressionPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
