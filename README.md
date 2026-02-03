# x-term (X gate)

Blocks browsing X/Twitter (`x.com`, `twitter.com`, `t.co`) in Google Chrome while **Codex** or **Claude Code** is running in a terminal (TTY).

## How it works

- A **Chrome Manifest V3 extension** adds/removes a `declarativeNetRequest` rule that redirects X/Twitter to a local “Blocked” page.
- A **native messaging host** (`native-host/process_gate.py`) watches processes and reports whether `codex` or `claude` is running with a real TTY.

## Install (macOS / Linux)

1) Load the extension:
   - Chrome → `chrome://extensions`
   - Enable **Developer mode**
   - **Load unpacked** → select `chrome-extension/`
   - Copy the extension ID

2) Register the native host (writes the native host manifest for Chrome):

```bash
python3 native-host/install.py --extension-id YOUR_EXTENSION_ID
```

3) Restart Chrome.

## Test

- Start `codex` or `claude` from a terminal.
- Navigate to `https://x.com` → you should see the block page.
- Quit the process → within ~1–2 seconds, navigation should work again.

## Debug

```bash
python3 native-host/process_gate.py --check
python3 native-host/process_gate.py --watch-stdio
python3 native-host/smoke_test.py
```

## Configure

Edit `native-host/process_gate.config.json`:

- `watch_regex`: regex used to detect Codex/Claude
- `require_tty`: only count processes with a TTY
- `poll_interval_seconds`: polling cadence
- `heartbeat_seconds`: status message cadence (keeps the extension worker alive)
