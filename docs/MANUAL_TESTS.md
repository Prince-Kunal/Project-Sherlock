# Manual tests

Things the automated tests can't cover because they need a real Google account. Run them after
changing sign-in, sending or reply tracking, and note the date and result in the progress log
(`docs/PLAN.md` §14).

## Phase 7: real Gmail send, attachment, reply detection

You need two email addresses you can read: your main Gmail (the **sender**, signs in to Sherlock)
and a second address (the **recipient**, any provider).

### One-time Google Cloud setup

1. At <https://console.cloud.google.com> create a project named **Sherlock**.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **Google Auth Platform → Branding**: app name **Sherlock**, your address as support and
   developer contact.
4. **Audience**: user type **External**, publishing status **Testing**. Under **Test users** add the
   sender address (and later each friend's address).
5. **Data access → Add or remove scopes**: `openid`, `.../auth/userinfo.email`,
   `.../auth/userinfo.profile`, `.../auth/gmail.send`, `.../auth/gmail.readonly`.
6. **Clients → Create client**: type **Web application**, authorised redirect URI
   `http://localhost:3000/api/auth/google/callback`.
7. In `.env` (never commit it):

   ```
   GOOGLE_CLIENT_ID=<client id>
   GOOGLE_CLIENT_SECRET=<client secret>
   ADMIN_EMAILS=["<sender address>"]
   USE_FAKES=false      # real Gmail; the real Gemini and Hunter keys are used too
   ```

8. `make up`.

In Testing mode Google expires the authorisation after about 7 days. Sherlock then shows a
"Reconnect Gmail" banner and holds scheduled emails until you reconnect; nothing is lost.

### The test

1. Open <http://localhost:3000/login> and click **Sign in with Google** with the sender address.
   Google warns the app is unverified (expected in Testing mode): **Continue**. Tick **both** Gmail
   boxes on the permissions screen.
   - Expect: you land on the review queue, no "Gmail isn't connected" banner, and
     Settings → Sending shows **Gmail connected**.
2. Get one draft to review with the recipient as the contact: on the Jobs page pick a match, click
   **Draft now**, then on the review card use **Change contact** and enter the recipient address.
   (Use a job at a company you don't mind being associated with in the subject line; the email only
   goes to your own second address.)
3. Read the draft, fix anything, and click **Approve and send**.
   - Expect: the card says when it goes out. Approved emails only go out **on weekdays** inside
     your send window (Profile and resume → preferences, in your timezone); to test now, set the
     window to include the current time. On a weekend it is scheduled for Monday morning.
4. Wait for the slot (3–12 minutes after approval; the sender job runs every 5 minutes).
   - Expect: the Outreach tracker shows it under **Sent** with the time.
   - In the recipient's inbox: the email from the sender's name and address, the subject and body
     exactly as approved, the opt-out line, and `Firstname_Lastname_Resume.pdf` attached. Open the
     PDF and check it's the tailored one (one page, selectable text).
   - In the sender's Gmail **Sent** folder: the same email.
5. From the recipient address, **reply** to that email with one line, e.g. "Happy to refer you".
6. Within 30 minutes (the reply checker runs at :11 and :41 past each hour):
   - Expect: the tracker moves it to **Replied**; the detail drawer's history shows "Reply received"
     with your line (without the quoted original).
7. Optional, opt-out: repeat steps 2–5 with a different job and reply "please remove me".
   - Expect: the outreach is **Closed**, and Change contact with that address is refused with "This
     address asked not to be contacted."

### Record the real thread as a fixture

So the reply tests run against a real Gmail response instead of the synthetic one, record the
thread from step 5 (find the outreach id in the tracker URL or the API):

```
cd backend
uv run python -m tests.fixtures.record_sources gmail <outreach_id> thread_reply
```

Addresses and names of both people are replaced with the fixture persons'; check the diff before
committing, then run `make test`.

### Clean up

Delete the test emails if you like. To revoke Sherlock's access: Settings → Sending →
**Disconnect** (or <https://myaccount.google.com/permissions>).

## Phase 9: a second user onboards end to end (after deployment)

The Phase 9 acceptance criterion "a second test user can go through onboarding end to end on the
deployed instance" waits for the deployment task. The same flow was run on fakes (API level, local
host, 2026-10-12). On the deployed instance:

1. As the owner, open **Admin → People** and add the friend's Gmail address. In the Google Cloud
   console, add the same address under **Audience → Test users** (Testing mode refuses others).
2. In a private window, sign in as the friend. Expected: Sherlock opens **/welcome**, not the review
   queue, and the stepper starts at **Connect Gmail** only if the Gmail boxes were unticked.
3. Add the friend's own Gemini key, then their Hunter key (or skip it and see the warning).
4. Upload their resume, check what was read, fix anything and save, then **Looks right**.
5. Set at least one target role and employment type, save, **Continue**, **Start the first run**.
   Expected: the review queue opens; within a few minutes drafts appear (as many as the jobs that
   fit allow, up to the daily batch).
6. As the owner, **Admin → Usage**: the friend's row shows LLM requests and contact lookups, and
   "setting up" is gone.
7. As the friend, **Settings → Delete my data**, type the address. Expected: back on the login page
   with the "Your data was deleted" note; the friend is gone from Admin → Usage; at
   <https://myaccount.google.com/permissions> Sherlock no longer has access.

## Phase 10: browser extension and weekly summary

**Extension** (`extension/README.md` has the install steps):

1. Load `extension/` unpacked in Chrome and set its address to your Sherlock (default
   `http://localhost:3000`). Be signed in to Sherlock in the same browser.
2. Open a Greenhouse, Lever, Ashby, SmartRecruiters, Workable or Recruitee posting and click the
   toolbar button. Expected: a Sherlock tab at `/add-job` says "Added to Sherlock" with the title
   and company, and the job is on the Jobs page (source "Added by URL").
3. On any other job page (a company's own careers page), the same works but uses your Gemini key.
4. Right-click a job link on a list page → "Send this job link to Sherlock": same result without
   opening the posting.

**Weekly summary:** with real Gmail connected and something sent or waiting in the last week, the
worker sends it on Monday 08:30 your time. To try it now, run in the backend container:
`python -c "import asyncio; from app.workers.settings import send_weekly_summaries; print(asyncio.run(send_weekly_summaries({})))"`
at 08:xx on a Monday, or call `app.services.email.summary.send_summary` directly. Expected: an
email from you to yourself with the week's numbers and a link to the review queue; switching
"Weekly summary email" off in Settings → Schedule stops it.
