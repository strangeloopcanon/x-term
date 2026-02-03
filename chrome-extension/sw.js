const NATIVE_HOST = "com.xterm.processgate";
const KEEPALIVE_ALARM = "xterm-keepalive";

const RULES = [
  { id: 1, urlFilter: "||x.com^" },
  { id: 2, urlFilter: "||twitter.com^" },
  { id: 3, urlFilter: "||t.co^" }
];

const BLOCKED_URL = chrome.runtime.getURL("blocked.html");

// Badge colors
const BADGE_BLOCKING = { text: "X", color: "#dc2626" }; // Red - blocking
const BADGE_ALLOWED = { text: "", color: "#16a34a" }; // Green - allowed
const BADGE_DISCONNECTED = { text: "!", color: "#6b7280" }; // Gray - disconnected

function updateBadge(blocking, connected) {
  if (!connected) {
    chrome.action.setBadgeText({ text: BADGE_DISCONNECTED.text });
    chrome.action.setBadgeBackgroundColor({ color: BADGE_DISCONNECTED.color });
    chrome.action.setTitle({ title: "X Gate: Native host disconnected" });
  } else if (blocking) {
    chrome.action.setBadgeText({ text: BADGE_BLOCKING.text });
    chrome.action.setBadgeBackgroundColor({ color: BADGE_BLOCKING.color });
    chrome.action.setTitle({ title: "X Gate: Blocking (Codex/Claude running)" });
  } else {
    chrome.action.setBadgeText({ text: BADGE_ALLOWED.text });
    chrome.action.setBadgeBackgroundColor({ color: BADGE_ALLOWED.color });
    chrome.action.setTitle({ title: "X Gate: Allowed" });
  }
}

function dnrUpdateDynamicRules(update) {
  return new Promise((resolve, reject) => {
    chrome.declarativeNetRequest.updateDynamicRules(update, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

function buildBlockRules() {
  return RULES.map(({ id, urlFilter }) => ({
    id,
    priority: 1,
    action: { type: "redirect", redirect: { url: BLOCKED_URL } },
    condition: { urlFilter, resourceTypes: ["main_frame"] }
  }));
}

let port = null;
let currentBlock = true; // fail-closed until the native host tells us otherwise
let lastStatus = null;

let nextPollId = 1;
const pendingPolls = new Map(); // id -> { resolve, reject, timeout }

async function setBlock(block, source = "unknown") {
  if (currentBlock === block) return;
  currentBlock = block;

  if (block) {
    await dnrUpdateDynamicRules({
      removeRuleIds: RULES.map((r) => r.id),
      addRules: buildBlockRules()
    });
  } else {
    await dnrUpdateDynamicRules({
      removeRuleIds: RULES.map((r) => r.id)
    });
  }

  lastStatus = {
    ...lastStatus,
    block_x: currentBlock,
    updated_at_unix: Date.now() / 1000,
    updated_by: source
  };

  // Update badge to reflect current state
  updateBadge(currentBlock, Boolean(port));
}

async function ensureKeepaliveAlarm() {
  return new Promise((resolve) => {
    chrome.alarms.get(KEEPALIVE_ALARM, (existing) => {
      if (!existing) chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 1 });
      resolve();
    });
  });
}

function resolvePoll(reply) {
  if (!reply || typeof reply.reply_to !== "number") return;
  const pending = pendingPolls.get(reply.reply_to);
  if (!pending) return;
  clearTimeout(pending.timeout);
  pendingPolls.delete(reply.reply_to);
  pending.resolve(reply);
}

function connectNative() {
  if (port) return;

  try {
    port = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (err) {
    console.error("connectNative failed:", err);
    setBlock(true, "connectNative-failed").catch(console.error);
    port = null;
    return;
  }

  port.onMessage.addListener((msg) => {
    resolvePoll(msg);

    if (msg && typeof msg.block_x === "boolean") {
      lastStatus = { ...msg, received_at_unix: Date.now() / 1000 };
      // Update badge first to show connected state
      updateBadge(Boolean(msg.block_x), true);
      setBlock(Boolean(msg.block_x), "native-status").catch(console.error);
    }
  });

  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError;
    if (err) console.warn("Native host disconnected:", err.message);
    port = null;
    updateBadge(true, false); // Show disconnected state
    setBlock(true, "native-disconnect").catch(console.error);
  });

  port.postMessage({ type: "hello" });
}

function pollNativeOnce(timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    connectNative();
    if (!port) {
      reject(new Error("No native port"));
      return;
    }

    const id = nextPollId++;
    const timeout = setTimeout(() => {
      pendingPolls.delete(id);
      reject(new Error("poll timeout"));
    }, timeoutMs);

    pendingPolls.set(id, { resolve, reject, timeout });
    port.postMessage({ type: "poll", id });
  });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== KEEPALIVE_ALARM) return;
  connectNative();
  try {
    port?.postMessage({ type: "ping" });
  } catch (err) {
    console.warn("keepalive ping failed:", err);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return;

  if (msg.type === "get_status") {
    sendResponse({
      block_x: currentBlock,
      last_status: lastStatus,
      native_connected: Boolean(port)
    });
    return;
  }

  if (msg.type === "poll_status") {
    pollNativeOnce()
      .then((reply) => {
        sendResponse({
          ok: true,
          reply,
          block_x: currentBlock,
          last_status: lastStatus,
          native_connected: Boolean(port)
        });
      })
      .catch((err) => {
        sendResponse({
          ok: false,
          error: String(err && err.message ? err.message : err),
          block_x: currentBlock,
          last_status: lastStatus,
          native_connected: Boolean(port)
        });
      });
    return true;
  }
});

async function boot() {
  await ensureKeepaliveAlarm();
  updateBadge(true, false); // Initial state: blocking, not connected
  await setBlock(true, "boot"); // fail-closed until we hear from native host
  connectNative();
}

boot().catch((err) => console.error("boot failed:", err));
