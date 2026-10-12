"use client";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api";
import { googleSignInUrl } from "@/lib/auth";
import {
  useDisconnectGmail,
  useGmailStatus,
  usePreferences,
  useSavePreferences,
} from "@/lib/queries";

/** Phase 7: Gmail connection and the pause switch. */
export function SendingCard() {
  const gmail = useGmailStatus();
  const prefs = usePreferences();
  const save = useSavePreferences();
  const disconnect = useDisconnectGmail();
  const status = gmail.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Sending
          {status &&
            (status.connected ? (
              <Badge>Gmail connected</Badge>
            ) : status.needs_reauth ? (
              <Badge variant="destructive">Reconnect Gmail</Badge>
            ) : (
              <Badge variant="secondary">Gmail not connected</Badge>
            ))}
        </CardTitle>
        <CardDescription>
          Approved emails go out from {status?.email ?? "your Gmail"}, spaced 3
          to 12 minutes apart inside your send window on weekdays, never more
          than your daily cap.
          {prefs.data &&
            ` Window ${prefs.data.send_window_start.slice(0, 5)}–${prefs.data.send_window_end.slice(0, 5)}, cap ${prefs.data.daily_send_cap} a day.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {prefs.data && (
          <div className="flex items-center gap-3">
            <Switch
              id="paused"
              checked={prefs.data.paused}
              disabled={save.isPending}
              onCheckedChange={(paused) =>
                save.mutate(
                  { ...prefs.data, paused },
                  { onSuccess: () => void gmail.refetch() },
                )
              }
            />
            <Label htmlFor="paused" className="font-normal">
              Pause Sherlock (no new drafts, nothing sent)
            </Label>
          </div>
        )}
        {status?.google_sign_in && (
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={googleSignInUrl("/settings")}
              className={buttonVariants({
                variant: status.connected ? "outline" : "default",
                size: "sm",
              })}
            >
              {status.connected ? "Reconnect Gmail" : "Connect Gmail"}
            </a>
            {status.connected && (
              <Button
                variant="ghost"
                size="sm"
                disabled={disconnect.isPending}
                onClick={() => disconnect.mutate()}
              >
                Disconnect
              </Button>
            )}
          </div>
        )}
        {status && !status.google_sign_in && (
          <p className="text-muted-foreground text-sm">
            Google sign-in isn&apos;t set up on this server, so emails can only
            be sent to the fake mailbox (USE_FAKES=true).
          </p>
        )}
        {(save.isError || disconnect.isError) && (
          <p className="text-destructive text-sm">
            {errorMessage(save.error ?? disconnect.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
