# Send to Sherlock (browser extension)

Adds the job posting you're looking at to your Sherlock job list (PLAN.md Phase 10).

- **Toolbar button:** sends the page you're on.
- **Right-click a link → "Send this job link to Sherlock":** sends that link without opening it.

It opens `<your Sherlock>/add-job?url=…`, and that page adds the job through `POST /jobs/manual`
with your normal signed-in session. The extension holds no password, token or API key, can't read
pages (it only sees a tab's URL when you click it), and talks to nothing but your own Sherlock.
Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Recruitee links are read through those
boards' public APIs; any other page is read by your Gemini key, like a pasted link.

## Install (Chrome, Edge, Brave, Arc)

1. Open `chrome://extensions` and switch on **Developer mode**.
2. **Load unpacked** → choose this `extension/` folder.
3. Open the extension's **Options** and set your Sherlock address (default `http://localhost:3000`).
4. Sign in to Sherlock once in the same browser.
