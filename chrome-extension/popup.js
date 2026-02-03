/**
 * Popup UI for X Gate extension settings.
 */

const invertCheckbox = document.getElementById("invert");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");

// Load saved setting
chrome.storage.local.get(["invert"], (result) => {
  // Default to true (reward mode)
  invertCheckbox.checked = result.invert !== false;
});

// Save on change and notify service worker
invertCheckbox.addEventListener("change", () => {
  const invert = invertCheckbox.checked;
  chrome.storage.local.set({ invert });
  chrome.runtime.sendMessage({ type: "set_invert", invert });
});

// Get current status
async function updateStatus() {
  try {
    const status = await chrome.runtime.sendMessage({ type: "get_status" });
    
    if (!status.native_connected) {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Native host disconnected";
    } else if (status.block_x) {
      statusDot.className = "status-dot blocking";
      statusText.textContent = "X is blocked";
    } else {
      statusDot.className = "status-dot allowed";
      statusText.textContent = "X is allowed";
    }
  } catch (err) {
    statusDot.className = "status-dot disconnected";
    statusText.textContent = "Error: " + err.message;
  }
}

updateStatus();
