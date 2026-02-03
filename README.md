# x-term (X gate)

Controls access to X/Twitter (`x.com`, `twitter.com`, `t.co`) in Google Chrome based on whether **Codex** or **Claude Code** is running in a terminal.

**Default behavior (invert: true):** X is *allowed* while Codex/Claude is running, *blocked* when not working.

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

| Option | Default | Description |
|--------|---------|-------------|
| `invert` | `true` | If true: block X when Codex/Claude is NOT running (reward mode). If false: block when running (focus mode). |
| `watch_regex` | `(?i)\b(codex\|claude...)\b` | Regex to detect Codex/Claude processes |
| `require_tty` | `true` | Only count processes attached to a real terminal |
| `poll_interval_seconds` | `1.0` | How often to check for processes |
| `heartbeat_seconds` | `15.0` | Status message cadence (keeps extension alive)

## Logs

Logs are written to `~/Library/Logs/x-term/process_gate.log` (macOS) or `~/.cache/x-term/process_gate.log` (Linux).
