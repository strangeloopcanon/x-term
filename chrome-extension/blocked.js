function fmt(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

async function getStatus() {
  return chrome.runtime.sendMessage({ type: "get_status" });
}

async function pollStatus() {
  return chrome.runtime.sendMessage({ type: "poll_status" });
}

function setStatus(text) {
  const el = document.getElementById("status");
  el.textContent = text;
}

async function refresh() {
  const base = await getStatus().catch((err) => ({ error: String(err) }));
  setStatus(fmt(base));

  const polled = await pollStatus().catch((err) => ({ error: String(err) }));
  setStatus(fmt(polled));
}

document.getElementById("check").addEventListener("click", () => {
  refresh().catch((err) => setStatus(String(err)));
});

refresh().catch((err) => setStatus(String(err)));

