// "Send to Sherlock" (PLAN.md Phase 10). The extension never handles credentials or calls the API
// itself: it opens Sherlock's /add-job page with the job's URL, and that page adds the job using your
// normal signed-in session. Permissions: activeTab (read the current tab's URL only when clicked),
// contextMenus (right-click a link) and storage (remember your Sherlock address).

const DEFAULT_BASE = "http://localhost:3000";

async function sherlockBase() {
  const { base } = await chrome.storage.sync.get({ base: DEFAULT_BASE });
  return String(base).replace(/\/+$/, "");
}

async function sendToSherlock(url) {
  if (!/^https?:\/\//i.test(url || "")) return; // chrome://, file:// and the like aren't job pages
  const base = await sherlockBase();
  await chrome.tabs.create({ url: `${base}/add-job?url=${encodeURIComponent(url)}` });
}

chrome.action.onClicked.addListener((tab) => sendToSherlock(tab.url));

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-link-to-sherlock",
    title: "Send this job link to Sherlock",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "send-link-to-sherlock") sendToSherlock(info.linkUrl);
});
