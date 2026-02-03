/**
 * Blocked page UI logic for X Gate extension.
 * Shows human-readable status and controls the "Open X" button visibility.
 */

async function getStatus() {
  return chrome.runtime.sendMessage({ type: "get_status" });
}

async function pollStatus() {
  return chrome.runtime.sendMessage({ type: "poll_status" });
}

function formatTime(unixSeconds) {
  if (!unixSeconds) return "unknown";
  const date = new Date(unixSeconds * 1000);
  return date.toLocaleTimeString();
}

function updateUI(status) {
  const statusEl = document.getElementById("status");
  const openBtn = document.getElementById("open-x");

  if (status.error) {
    statusEl.textContent = `Error: ${status.error}`;
    openBtn.style.display = "none";
    return;
  }

  const blocking = status.block_x;
  const connected = status.native_connected;
  const lastUpdate = status.last_status?.timestamp_unix;

  let message = "";

  if (!connected) {
    message = "Native host not connected. X is blocked by default.";
    openBtn.style.display = "none";
  } else if (blocking) {
    message = "Codex or Claude is running. X remains blocked.";
    openBtn.style.display = "none";
  } else {
    message = "No Codex/Claude detected. X is now accessible.";
    openBtn.style.display = "inline-block";
  }

  if (lastUpdate) {
    message += `\nLast checked: ${formatTime(lastUpdate)}`;
  }

  statusEl.textContent = message;
}

async function refresh() {
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Checking...";

  try {
    // First get cached status
    const base = await getStatus();
    updateUI(base);

    // Then poll for fresh status
    const polled = await pollStatus();
    if (polled.ok) {
      updateUI(polled);
    } else {
      updateUI({
        block_x: polled.block_x,
        native_connected: polled.native_connected,
        last_status: polled.last_status,
        error: polled.error
      });
    }
  } catch (err) {
    updateUI({ error: String(err) });
  }
}

document.getElementById("check").addEventListener("click", () => {
  refresh();
});

// Initial check on page load
refresh();
