const input = document.getElementById("base");
const status = document.getElementById("status");

chrome.storage.sync.get({ base: "http://localhost:3000" }, ({ base }) => {
  input.value = base;
});

document.getElementById("save").addEventListener("click", () => {
  let url;
  try {
    url = new URL(input.value.trim());
  } catch {
    status.textContent = "Enter a full address, like http://localhost:3000";
    return;
  }
  if (!/^https?:$/.test(url.protocol)) {
    status.textContent = "Use an http or https address";
    return;
  }
  chrome.storage.sync.set({ base: url.origin }, () => {
    input.value = url.origin;
    status.textContent = "Saved";
  });
});
