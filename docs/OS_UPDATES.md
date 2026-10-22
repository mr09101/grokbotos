# OS updates and rollback

Grok Bot OS is a bootc image: an update replaces the whole read-only `/usr` at once, and the image you ran before stays on disk as the **rollback** deployment (Omarchy-style: one switch forward, one switch back). `/etc` and `/var` (your home) carry over.

## What the user sees

- **Dock:** an update icon when a check found a new image (`software-update-available`, highlighted), or a restart icon when one is installed and waits for a restart. Click: Settings > Update.
- **Notification:** once per new image ("업데이트가 있습니다 / Update available"), and once, critical, if an update was rolled back automatically.
- **Settings > Update (업데이트):** state line, last check and last action; **Check for updates**, **Install update**, **Restart now** (power.action reboot); cards for the running, staged and previous image (image ref, version label, digest, build time) with **Roll back**; a banner if the health check rolled back.

Nothing installs or reboots by itself. Fedora's `bootc-fetch-apply-updates.timer` (download, stage, reboot) is masked. `grokbot-update-check.timer` only checks: 10 min after boot, then every 6 h.

## Pieces

| Piece | Runs as | Does |
|---|---|---|
| `grokbot-update@{status,check,apply,rollback}.service` → `/usr/lib/grokbot/grokbot_update.py` | root | `bootc status --format=json`, `bootc upgrade --check`, `bootc upgrade` (stage only), `bootc rollback`. Writes `/run/grokbot-update/{status,check,last}.json` (0644, no secrets). One at a time (flock) |
| `/usr/share/polkit-1/rules.d/50-grokbot-update.rules` | polkit | The active local session user may **start** those four units, nothing else (no stop, no other units) |
| grokbotd `update.*` | session user | `update.status` reads the files above and the health record. `update.check` / `update.apply` / `update.rollback` start a unit (`--no-block`, poll status). Scope `updates` is power-class (`ALWAYS_ASK`): every write prompts with Deny / Allow once only, for every caller |
| `grokbot-update-status.service` | root, at boot | records the deployments for the session |
| `grokbot-health-check.service` → `grokbot_health.py` | root, after graphical.target | the post-update health check below |

## Health check and automatic rollback

Greenboot-style, but small and specific to this OS. After `graphical.target`, it waits up to `timeout_s` (default 300) for a user session where **sway runs and that user's grokbotd answers** on `/run/user/<uid>/grokbot/api.sock`.

- Healthy: the booted digest becomes `last_good` (`/var/lib/grokbot-health/state.json`).
- Not healthy on a **new** image (not `last_good`, and not the first boot ever): record why, `bootc rollback`, reboot into the previous image. grokbotd then notifies and Settings shows the banner.

Loop guards: a digest is rolled back from **at most once**; the last-good image is never rolled back from; nothing happens without a rollback deployment that differs from the booted one; `grokbot.health=off` on the kernel command line or `enabled=false` in `/etc/grokbot/health.conf` (`[health]`, also `timeout_s`, `interval_s`) turns it off. Logs: `journalctl -u grokbot-health-check`.

## CLI

```
grokbot-os call update.status
systemctl start grokbot-update@check.service     # what the timer runs; no prompt (polkit only)
sudo bootc status / upgrade / rollback           # the underlying tool, still works
```

## Testing in the VM (tools/vm)

`tools/vm/update-test.sh` builds small images on top of the local one, pushes them to a local registry the VM reaches as `10.0.2.2:5000`, and writes a test disk whose updates come from there (`--target-imgref`). See the script header.
