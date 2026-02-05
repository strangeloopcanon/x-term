# x-term (X gate)

So what: a **global X/Twitter gate** that flips based on whether **Codex or Claude Code is actively working**.
It edits `/etc/hosts` via a tiny root daemon, and you control it from a CLI or a menu bar toggle.

## Quick start (macOS)

1) Create your config:

```bash
./bin/xgate init
```

2) Install the daemon (requires sudo):

```bash
sudo ./bin/xgate daemon install
```

3) (Optional) Install the menu bar toggle (requires [SwiftBar](https://swiftbar.app)):

```bash
./bin/xgate menubar install
```

4) Check status:

```bash
./bin/xgate status
```

## How it decides ALLOW vs BLOCK

There are two knobs:

- **Enabled**: master switch.
- **Reward mode**: which side counts as the “reward”.

When **Enabled is Off**, the gate does nothing (X/Twitter is allowed).

When **Enabled is On**, the gate watches Codex/Claude and treats it as either:

- **Active**: doing work right now
- **Idle**: open, but waiting on you / not doing work

Then it applies this rule:

| Enabled | Reward mode | Active | Idle |
| --- | --- | --- | --- |
| Off | (either) | ALLOW | ALLOW |
| On | On | ALLOW | BLOCK |
| On | Off | BLOCK | ALLOW |

In plain English:

- **Reward mode ON**: “I can browse X while I’m working; block it when I’m not.”
- **Reward mode OFF**: “Block X while I’m working; allow it otherwise.”

## Daily commands

```bash
./bin/xgate reward on
./bin/xgate reward off
./bin/xgate enable
./bin/xgate disable
./bin/xgate blocklist add x.com
./bin/xgate blocklist add --prompt
./bin/xgate blocklist list
./bin/xgate chrome reset-network
./bin/xgate chrome restart
```

## Config

Default config path:

- macOS: `~/Library/Application Support/x-gate/config.json`

Override with:

```bash
XGATE_CONFIG=/path/to/config.json ./bin/xgate status
```

### Default blocklist

`x.com`, `twitter.com` (plus `www.` variants).

<details>
<summary>▶ Notes and caveats</summary>

- Editing `/etc/hosts` is global (affects all apps).
- DNS cache is flushed on changes (macOS).
- Chrome can keep DNS/sockets/tabs alive across flips; use `./bin/xgate chrome reset-network` (or `./bin/xgate chrome restart`) to apply immediately.
- SwiftBar plugin refreshes every ~10 seconds (`xgate.10s.sh`).
- After pulling code updates, run `sudo ./bin/xgate daemon install` once so launchd picks up the new daemon build.
- If Chrome uses Secure DNS with a custom resolver, hosts-based blocking can be inconsistent.
- Cancelling the domain prompt leaves your blocklist unchanged.

</details>
