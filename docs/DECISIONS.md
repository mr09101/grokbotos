# Decisions Log

2026-10-18부터 새 항목은 한국어로 적는다. 그 아래 영어 기록은 AI-OS 시절의
원문이다. 실기에서 얻은 수정이라 고치지 않는다. Grok Bot OS 전환은 이 파일
맨 아래 2026-10-18 항목이다.

Tracks the Phase 0/1 decisions called for by the original roadmap, and why.
Append new decisions here rather than losing them in commit messages.

## Base distro: Fedora Atomic (Universal Blue)

`ROADMAP.md` Phase 0 recommends this over an experimental Arch bootc setup
because Universal Blue has the most mature bootc tooling, docs, and
community. No reason to deviate for an MVP.

## Base image: `quay.io/fedora/fedora-bootc` (was `ghcr.io/ublue-os/base-main`, reversed 2026-07-09)

**Superseded, see below for the current choice.** Original reasoning
(still valid for why not Bazzite/Aurora/Bluefin): `ublue-os/image-template`'s
default `Containerfile` points at `ghcr.io/ublue-os/bazzite:stable`, a full
gaming-oriented desktop image. That's the wrong foundation here: Phase 4 of
the roadmap throws away the desktop entirely and replaces it with a
dedicated fullscreen prompt/voice shell (no icons, no taskbar). Starting
from a full GNOME/KDE desktop today just means stripping it back out later.
`base-main` was chosen as Universal Blue's minimal image with no desktop
environment, meant as a starting point for exactly this kind of build.

**Why it was reversed**: `ghcr.io/ublue-os/base-main` only publishes an
amd64 build (confirmed directly -- `docker manifest inspect` returns a
single-architecture manifest, not a multi-arch index). That silently
blocks building or testing this image on arm64 at all, which only surfaced
once the user (on an Apple Silicon Mac) actually tried to build an arm64
disk image and `bootc-image-builder` failed on the architecture mismatch.
This should have been checked before recommending an arm64 test path in
the first place, not discovered several failed CI runs in.

Switched to `quay.io/fedora/fedora-bootc:latest` -- plain upstream Fedora's
bootc image, published multi-arch (x86_64 + aarch64, per Fedora bootc/CoreOS
infrastructure and corroborated via web search; **not independently
verified by digest inspection**, since this dev sandbox's network policy
blocks `quay.io` outbound -- see `curl -sS "$HTTPS_PROXY/__agentproxy/status"`).
Not pinned to a digest yet for the same reason; pin it once resolvable from
an unrestricted network (CI logs, or the user's own machine). Cost of this
switch: lose Universal Blue's own tooling/update scripts baked into
`base-main` -- acceptable since the current Containerfile doesn't use any
of it (`dnf5 install` + a `systemctl enable`), and Phase 4 replaces the
desktop/update UX anyway.

## Template source: inlined, not forked separately

`ROADMAP.md` Phase 0 says to fork `ublue-os/image-template` to get the base
template. Since the working repo (`head77x/oais`, renamed to `head77x/grokbotos` on 2026-10-21) already existed as the
designated target, the template's files were copied directly into it
instead of maintaining a second forked repository — same result (a working
Containerfile/Justfile/CI baseline), one fewer repo to keep in sync.

## `/etc/os-release` branding approach

`base.sh` `sed`s `NAME`/`PRETTY_NAME` in `/usr/lib/os-release` (which
`/etc/os-release` symlinks to) but leaves `ID`/`ID_LIKE` as `fedora`. This
matches how Bazzite/Aurora/Bluefin brand themselves — package managers,
`bootc`, and other tooling key off `ID`, so changing it breaks things for no
benefit at this stage. `VARIANT`/`VARIANT_ID`/`HOME_URL` are added instead.

## LLM connection model (2026-07-08, ROADMAP.md 2.2): hybrid, auth-based cloud + auto-installed local

Neither pure cloud API keys nor pure local-only was chosen. Both modes are
supported, but the UX for each is deliberately not the obvious default:

- **Cloud providers**: no raw API key entry. The user connects an account
  via a login/auth flow (like `claude login`/`gh auth login`), not by
  pasting a key into a config file. `orchestrator/orchestrator/providers/cloud_oauth.py`
  implements the generic OAuth 2.0 Device Authorization Grant (RFC 8628)
  state machine this requires -- request a device code, show the user a
  `verification_uri`/`user_code`, poll the token endpoint until authorized.
  It is provider-agnostic on purpose: **no specific provider (Anthropic,
  OpenAI, Google, ...) is wired up yet**, because each one's actual
  device-flow endpoint URLs, client ID, and scopes need to be confirmed
  from that provider's real documentation before being hardcoded. Guessing
  those values would produce code that looks like it works but silently
  fails against the real service, which is worse than leaving it
  unimplemented. Concrete provider subclasses (`AnthropicAuthProvider`,
  etc.) are follow-up work, one at a time, each backed by that provider's
  actual published OAuth docs.
- **Local models**: if the user picks local, the OS should fetch and
  install the model itself, not send the user to a terminal.
  `orchestrator/orchestrator/providers/local_ollama.py` wraps the
  [Ollama](https://ollama.com) CLI (`ollama pull`/`ollama list`) for this
  -- Ollama was picked over raw llama.cpp/vLLM because it already has a
  one-command model pull/run story that matches "auto-installed" directly,
  and ROADMAP.md 2.2 already names it as a candidate. This is real
  subprocess-calling code, not a stub, but it can't be exercised in this
  dev sandbox (no `ollama` binary here -- see the section below) and needs
  verification on a real machine.

Which specific cloud providers to support, and the actual routing rule for
"하이브리드" (when to use cloud vs. local) are still open — this decision
only fixes the *shape* of both connection paths, not provider selection or
routing policy.

## Concrete cloud providers (2026-07-08, revised same day): wrap the official CLIs as subprocesses, don't touch their credentials

Anthropic and xAI both get the "install it, log in with your own account,
it just works" treatment the user asked for -- via the same mechanism for
both, `providers/cli_subprocess.py`: install the vendor's own official CLI,
let the user run its own login command, and call it as a subprocess
(`<cli> -p "<prompt>"`) for every completion. Neither provider reads a
credential file or calls a vendor REST API directly. The CLI handles 100%
of its own auth, invisibly to us, exactly as it would from a human's
terminal.

This replaces an earlier same-day version of this decision that had two
*different* mechanisms per vendor (Anthropic via a raw `x-api-key` REST
call, xAI via directly reading `~/.grok/auth.json` and calling
`api.x.ai` ourselves with the extracted token). That design was wrong for
what was actually being asked, not just suboptimal: reading and reusing a
CLI's own stored OAuth credential in a separate unofficial HTTP client is
the "spoof a client's identity" pattern Anthropic's Jan-Apr 2026
enforcement specifically targets (see below) -- running the official
binary itself is not that at all, and there was never a good reason to
treat xAI differently once that was clear.

- **`providers/claude_cli.py` (`ClaudeCliProvider`)**: wraps `claude -p`.
  Installed via `npm install -g @anthropic-ai/claude-code` if missing.
  This is unambiguously fine -- it's the same Claude Code binary and the
  same login (`claude login`) a user would use directly, just invoked by
  our orchestrator instead of typed by hand. The thing that *would* violate
  Anthropic's Consumer Terms of Service, and is enforced server-side since
  January 2026 (escalated April 2026, with account bans): extracting
  Claude Code's stored OAuth token and presenting it directly to
  `api.anthropic.com` from a separate, unofficial HTTP client -- which is
  what the previous version of this decision (and `AnthropicApiKeyProvider`
  used generically, not for that purpose) did not do, but is worth naming
  explicitly since it's the actual line. Sources: [Anthropic clarifies ban
  on third-party tool access to Claude (The
  Register)](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/),
  [Anthropic Ends Paid Access for Claude in Third-Party Tools Like OpenClaw
  (MLQ News)](https://mlq.ai/news/anthropic-ends-paid-access-for-claude-in-third-party-tools-like-openclaw/).
  `providers/anthropic_api_key.py` (official `x-api-key` REST auth, via
  the `SecretStore` interface) is kept as a fallback for setups without
  Claude Code installed -- this remains explicitly fine per Anthropic's own
  guidance, it's just no longer the primary path.

- **`providers/xai_grok.py` (`GrokCliProvider`)**: wraps
  `grok --no-auto-update -p`. Installed via
  `npm install -g @xai-official/grok` if missing. `--no-auto-update` is
  confirmed from the CLI's own documented smoke-test example
  (`grok --no-auto-update -p "Say ok."`). This also sidesteps the
  `~/.grok/auth.json` schema uncertainty the previous version of this
  provider had to work around -- we no longer read that file at all.

Both share `providers/cli_subprocess.py`'s `CliSubprocessProvider`:
`ensure_ready()` installs the CLI if absent, then runs a cheap real prompt
as a login-state smoke test (there's no reliably-named side-effect-free
"am I logged in" subcommand confirmed for either CLI) and caches success;
`complete_json()` embeds the JSON-schema instruction in the prompt text
(same pattern as the Ollama/xAI-REST/Anthropic-REST providers) and parses
stdout.

## Environment/CI limitations of this dev sandbox

This repo was scaffolded from a cloud dev container with no `/dev/kvm`, no
`podman`/`bootc`/`just`/`qemu` installed, and no privileged container
support (loop devices for `bootc-image-builder` need real root + KVM). That
means every "boot it and check" item in Phase 0/1 (`bootc status`, ISO
install test, `bootc switch` test) had to be left unchecked here and pushed
to `docs/LOCAL_SETUP.md` for the user's own machine. GitHub Actions
(`build.yml`/`build-disk.yml`) run on real `ubuntu-24.04` runners and don't
have this limitation — those are expected to work once secrets are set up.

## `build-disk.yml` fix: explicit `podman pull` before bootc-image-builder (2026-07-08)

First real run of `build-disk.yml` failed with `ghcr.io/head77x/oais:latest:
image not known` -- newer `bootc-image-builder` versions stopped pulling
the target image themselves and expect it already present in the same
podman storage the build step mounts. Added a `docker/login-action` step
(the package is private, tied to this private repo) plus an explicit
`sudo podman pull ...` step before the build step, matching the error
message's own suggested fix. Only found by actually running the workflow
-- this wasn't something to catch by reading the template beforehand.

Two more issues surfaced on subsequent runs, same pattern (only found by
actually executing the workflow):

- `docker/login-action` logs in the runner user's own credential store,
  but the pull (and bootc-image-builder itself) run as root via `sudo`,
  which keeps a separate one -- login reported success but the pull still
  got `unauthorized`. Fixed by logging in with `sudo podman login`
  instead, so both steps share root's credential store.
- `ghcr.io/ublue-os/base-main` doesn't declare a default root filesystem
  type in its container metadata, so bootc-image-builder failed with
  `missing required info: DefaultRootFs`. This is a known issue with
  Universal Blue-derived images (confirmed via their own Discourse forum,
  not guessed) -- fixed by passing `--rootfs ext4` explicitly via
  `additional-args`. (Left in place after switching to fedora-bootc too --
  explicit is still fine even if no longer strictly required.)

## arm64 image build + two more bugs found testing it (2026-07-09)

Following the base image switch above, `build.yml` now builds both
architectures natively via a `platform: [amd64, arm64]` matrix
(`ubuntu-24.04` / `ubuntu-24.04-arm` runners). amd64 and arm64 are pushed
as **separately-named images** (`oais` / `oais-arm64`), not merged into one
multi-arch manifest list -- simpler to reason about and debug than wiring
up cross-job digest aggregation for a manifest-list push, at the cost of
the registry not "just resolving the right arch" from a single tag.
Revisit if that's worth it later. `build-disk.yml` picks the matching
image name based on its `platform` input.

Two bugs found while wiring this up, both in `disk_config/iso.toml`:

- The kickstart's `bootc switch` target was hardcoded to
  `ghcr.io/head77x/oais:latest` -- on an arm64 build this would have
  switched an arm64-installed system to an amd64 image. `build-disk.yml`
  now `sed`s the correct image name in before the build step.
- `org.fedoraproject.Anaconda.Modules.Users` was in the installer's
  disabled-modules list (inherited from the `ublue-os/image-template`
  example this was based on, uncaught until now). With it disabled and no
  `user`/`rootpw` in the kickstart, an install would finish with **no way
  to log in** -- silently failing Phase 1's actual acceptance criterion.
  Removed from the disable list so Anaconda's normal interactive
  account-creation screen runs.

## Phase 4 boot shell + LLM connection onboarding (2026-07-09)

Reordered ahead of 2.7/2.8 at the user's direction: the closed-loop
pipeline is moot if there's no working way to actually connect an LLM
provider on a real installed system, so that gate needed to be solid
first, wired into the actual boot flow -- not just exercised as library
calls from a dev machine like everything in `orchestrator/` so far.

**`orchestrator/orchestrator/onboarding.py` + `onboarding_cli.py`**: the
provider-agnostic connection logic (pick a provider, drive its
install/login, remember the choice in `~/.config/oais/provider.json`) is
separated from the console UI on top of it, same DI-for-testability
pattern as the rest of `orchestrator/`. `onboarding_cli.py` is a real,
runnable, text-based flow verified in this dev sandbox (piped stdin) --
it's the console-only OS's actual Phase 2.1 입력 레이어 for now, not a
placeholder. Wrapping it in graphical chrome is a presentation-layer
concern the logic underneath doesn't care about.

**Claude vs. Grok connection shape, revised same day**: originally
(see the Anthropic/xAI research further up this doc) Claude was going to
use a pasted `claude setup-token` since this OS had no browser and
`claude login` needs a local one. The user then decided the OS should
just ship a browser by default rather than route around not having one --
`docs/DECISIONS.md`'s job is to keep this kind of reversal visible, not
just the latest state. `connect_claude_via_browser()` is now the primary
path, same shape as `connect_grok()` (try silently, then run the login
command with real stdio so the CLI's own browser-opening behavior takes
over); `connect_claude_with_token()` stays as a fallback for before a
graphical session exists yet.

**Browser + minimal Wayland session baked into the image**: `firefox` +
`sway` (compositor) + `foot` (terminal) installed via `build_files/build.sh`,
matching Phase 4's "전용 컴포지터 기반 풀스크린 셸" -- one thing running
fullscreen (a terminal running `onboarding_cli.py`), no panel, no window
chrome; Firefox gets fullscreen too when the shell spawns it for login,
and focus returns to the shell when it closes. A dedicated `aios` system
account runs this, independent of whatever admin username Anaconda's
interactive kickstart creates at install time (nothing in the image can
know that name in advance).

**Caught before committing, not after another failed CI-style round
trip**: `/opt` and `/home` are symlinked to `/var/opt`/`/var/home` on
this ostree/bootc base, and `/var` content written during the image
build isn't guaranteed to survive into the shipped image (the
Containerfile template this project started from even has a comment
about exactly this for `/opt`). The original draft of this change put
the app under `/opt/oais` and the kiosk config under
`~aios/.config/sway/` and `~aios/.bash_profile` -- all of which could
have silently vanished on first boot. Moved to `/usr/lib/oais/orchestrator`
(app code), `/etc/sway/config` (system-wide sway config instead of
per-user), and a login-shell script at `/usr/local/bin/oais-shell-launch`
(instead of `.bash_profile`) -- `/usr` and `/etc` are the parts of an
ostree/bootc image actually guaranteed to persist.

**Still genuinely unverified**: this dev sandbox has no display to boot
a graphical session against at all. Autologin-into-sway pattern, the
sway config, SELinux policy (Fedora bootc ships enforcing by default,
and none of this was written with a specific SELinux module in mind) --
all written from documented patterns, none boot-tested. Expect at least
one round of fixes once actually tried in the VM, same as
`build.yml`/`build-disk.yml` needed.

## Phase 4 boot shell: text TUI replaced with a real GUI web shell (2026-07-10)

The first boot-tested build (arm64 disk image, `main`@`a266e5f`) actually
worked -- tty1 autologin -> sway -> the onboarding shell ran and showed
its provider-selection screen. Two problems surfaced from that first real
test, both from actual screenshots the user provided:

**1. Korean text rendered as tofu boxes.** The image had no CJK-capable
font installed, so `foot` fell back to boxes for any Hangul the shell
printed. Fixed by adding `google-noto-sans-cjk-ttc-fonts` to `build.sh`'s
`dnf5 install` line.

**2. Wrong UI shape entirely.** The shell that actually appeared was a
numbered text menu (`[1] Claude (Anthropic)` etc.) in a terminal. The
user's explicit expectation, stated after seeing the screenshot: once
AI-OS is installed, the *first* screen must be a desktop-style GUI --a
prompt input at the center, and a dock/taskbar-like row of icons at the
bottom for both installed programs and LLM-connection options. The
prompt input must be visibly disabled until an LLM icon is clicked and a
connection succeeds. A text menu in a terminal does not meet that bar,
regardless of how correct the underlying connection logic is.

**Decision: build this as a local HTTP server + static HTML/CSS/JS page,
displayed via the already-baked-in Firefox in `--kiosk` mode** --
rather than a native toolkit (GTK4, Qt). Reasoning:

- Firefox is already a hard requirement in the image (OAuth login for
  `claude`/`grok` needs a real browser -- see the entry above this one).
  Reusing it for the shell UI itself means no new heavyweight package
  (GTK4 + PyGObject + introspection data, or Qt + PySide) has to be
  added just to draw a box and some icons.
  `sway`'s existing `for_window [app_id="firefox"] fullscreen enable`
  rule already fullscreens whatever Firefox window is on screen, so the
  OAuth login flow (which also opens a Firefox window) and the shell
  itself share one visual language for free.
- The orchestrator package is already pure-stdlib Python (see its
  README's "stdlib only, on purpose" note); `http.server` keeps that
  true for the server side too, no new dependency to vendor or
  `dnf install`.
- HTML/CSS text rendering doesn't have the CJK tofu-box problem GTK/Qt
  can also hit if the wrong font stack is picked -- browsers fall back to
  system fonts (now including the Noto CJK package above) correctly by
  default.

**Shape of the result** (`orchestrator/webshell/`):
`server.py` (stdlib `http.server`, binds `127.0.0.1` only) serves
`static/index.html`+`style.css`+`app.js` and a small JSON API
(`/api/status`, `/api/apps`, `/api/choices`, `/api/connect`,
`/api/connect-token`, `/api/prompt`). `connect.py` runs the actual
connection flow (which blocks on a real subprocess during browser OAuth)
on a background thread, using a lock-protected `ConnectionState`
(`state.py`) so `/api/status` keeps answering polls while that's in
flight -- the frontend polls every 1.5s and enables the prompt input the
moment `connected` flips true. None of `onboarding.py`'s connection
logic changed; this only replaces the UI layer that was driving it.
`webshell_cli.py` is what `system_files/etc/sway/config` now execs
(replacing the old `foot -e ... onboarding_cli` line); `onboarding_cli.py`
itself is kept as-is for headless use (SSH, recovery console) since the
underlying logic is identical either way.

**Still genuinely unverified**: same caveat as before -- no display in
this dev sandbox. Logic-level tests only (`tests/test_webshell.py`,
including a real-socket integration test against routes that don't touch
subprocesses). The actual "click Claude icon -> Firefox OAuth window
opens on top -> closing it reveals the shell again with the prompt now
enabled" flow has never been observed end-to-end.

## Black screen after sway starts (2026-07-11) — home directory persistence bug

Second real boot report: tty1 autologin worked, the mouse cursor appeared
(so sway itself started and is compositing), but nothing else ever
rendered -- no window, no error, no way to check logs from within the
running session.

**Root cause (high-confidence, not yet confirmed against a real log --
see the logging fix below)**: `build.sh`'s `useradd --create-home aios`
creates `/var/home/aios` at image **build** time. This is exactly the
`/var`-doesn't-persist problem already documented above for `/opt` and
the app/config paths -- just missed for the user account's home
directory itself. At boot, `webshell_cli.py` (like everything under
`onboarding.py`) calls `Path.home()`-based paths (`~/.config/oais/`,
`~/.local/share/oais/`) and `mkdir(parents=True)`s into them. If
`/var/home/aios` doesn't exist, that walks up to the parent `/var/home`
-- owned `root:root`, mode `0755` -- and a non-root `aios` process trying
to create a subdirectory there gets `PermissionError`. That exception is
unhandled, so the process sway just `exec`'d crashes immediately, `exec`
(not `exec_always`) doesn't retry, and sway is left showing its own empty
background with nothing on it and no terminal to display the traceback.

**Fix, three parts**:

1. `system_files/usr/lib/tmpfiles.d/oais-aios-home.conf`: a
   `d /var/home/aios 0700 aios aios -` rule. Ships under `/usr`, so
   `systemd-tmpfiles-setup.service` (runs on every boot, standard systemd
   behavior, well before getty/autologin) recreates the directory with
   correct ownership regardless of what the build-time `useradd` did or
   didn't manage to persist. This is the actual fix, following the exact
   pattern ostree/bootc images already use to guarantee `/var/home`
   itself exists.
2. Debug logging: `system_files/etc/sway/config`'s `exec` line now
   redirects `webshell_cli`'s stdout/stderr (and Firefox's, since it's a
   subprocess sharing the same fds) to `$HOME/.local/share/oais/shell.log`
   instead of into the void. Next time something fails silently on
   screen, that file (readable from another VT, e.g. Ctrl+Alt+F2, or via
   an admin account) has the actual traceback.
3. `webshell_cli.py:_launch_firefox_or_fallback()`: if Firefox exits
   non-zero or isn't found, falls back to launching the old text shell
   (`foot -e ... onboarding_cli`) instead of leaving the screen blank --
   something visible (even a crude text menu) beats a silent hang, and
   it's driven by the exact same `Orchestrator`/`onboarding.py` logic
   either way.

**Still not fully confirmed**: without an actual log file from a real
boot, this is the most-likely-by-far explanation given the symptoms
(compositor definitely running, nothing else does), not a certainty --
there could be a second, unrelated issue (e.g. Firefox failing to
initialize GPU/GL rendering inside a QEMU/UTM VM with no acceleration,
which the new fallback would also mask into "text shell instead" rather
than surface directly). The logging added in part 2 is what turns the
next report from a guess into a real diagnosis.

## "Claude 클릭해도 반응 없음" — missing npm + a silently-dying background thread (2026-07-11)

Third real boot report, and genuine progress: the GUI web shell rendered
correctly this time (screenshot showed the prompt bar, the icon dock, and
the "연결 중..." status after clicking Claude) -- the tmpfiles/logging fix
above worked. But clicking Claude never went anywhere: no browser opened,
no error, stuck on "연결 중..." indefinitely.

**Root cause, found by re-reading the code (not yet confirmed against an
actual `shell.log`, since this session has no way to read the user's VM
directly)**: two independent bugs stacked.

1. `ClaudeCliProvider`/`GrokCliProvider`'s `install_argv` is
   `["npm", "install", "-g", "..."]` -- but `build.sh` never installs
   `nodejs`/`npm` in the image. `python3`, `sway`, `foot`, `firefox`, and
   the CJK font package are the only runtime packages it adds.
2. `webshell/connect.py:run_connect()` (and `run_connect_token()`) only
   caught `ExternalLoginRequired`/`ProviderNotReady`. `npm` missing means
   `subprocess.run(["npm", ...])` raises a bare `FileNotFoundError`,
   which neither `except` catches. This runs on a background thread
   (`server.py`'s `/api/connect` handler spawns it so `/api/status`
   polling keeps working during a real OAuth flow) -- an exception
   escaping a thread's target function doesn't crash the process, it just
   kills that thread silently. `ConnectionState` was left with
   `connecting="claude"` forever, since neither `set_connected()` nor
   `set_error()` ever ran. The frontend's polling loop was written
   correctly (show `status.error` when present) -- it just never got one.

**Fix**:
- `build.sh`: add `nodejs` (Fedora bundles npm with it) to the `dnf5
  install` line.
- `connect.py`: both functions now also catch a bare `Exception` after
  the specific ones, turning *any* unexpected failure into
  `state.set_error(...)` instead of a silently dead thread. This is the
  same lesson as the black-screen fix above, applied to a different
  failure mode -- don't let a background operation fail invisibly, no
  matter what actually goes wrong inside it.

**Still not confirmed against a real log** -- this is the most-likely
explanation given the code path and the observed symptom, not a
certainty. If this doesn't fully fix it, `shell.log` should now at least
show *something* useful either way, since Firefox/webshell_cli's own
stdout/stderr already gets captured there (the connect failure itself
happens inside the running webshell_cli process, so a `state.set_error()`
call doesn't show up in `shell.log` by itself -- that's surfaced through
the web UI's `#connect-status` text instead, which is the right place for
it to be visible to the user without needing a second console).

## Shell UI redesign + unified slash-command architecture (2026-07-11)

User feedback on the working GUI shell screenshot: the visual design was
"형편없다" (poor) compared to real product UI, and more importantly the
*architecture* didn't fit an "OS" -- clicking an icon (Claude 연결, Grok
연결, ...) ran bespoke JS that called a dedicated REST endpoint
(`/api/connect`), completely separate from what happened when the user
typed a prompt and pressed enter (`/api/prompt`). The user's explicit
instruction: **every icon must work by producing a prompt-pipeline
command** -- clicking "Claude 연결" and typing `/llm claude` + Enter must
be the *same request*, not two code paths that happen to have similar
effects. Referenced Claude Design's own prompt-input screen (dark
elevated card, centered prompt, thumbnail grid below) as the visual bar
to hit.

**Architecture change**: introduced `webshell/commands.py`, a slash-
command router. `POST /api/prompt` (the one endpoint everything now goes
through) checks whether `text` starts with `/`; if so it's dispatched to
`commands.dispatch()`, otherwise it goes to the real `Orchestrator` same
as before. `/api/connect` and `/api/connect-token` were deleted entirely
-- `commands.py` calls `connect.py`'s `run_connect()`/`run_connect_token()`
directly (still on a background thread, for the same reason as before:
`/llm claude` can block for minutes on a real browser OAuth flow, and
`/api/status` polling needs to keep working while that happens).

Built-in commands implemented, per the user's explicit list:
- `/llm [id]` -- list providers, or connect to one. `/llm custom <cli>
  [login_command...]` for the custom-CLI path (previously a multi-field
  form in the UI; now parsed from the command text itself, since a modal
  form doesn't fit "everything is a prompt").
- `/token claude <token>` -- the existing browser-login-failed fallback,
  now a command instead of a second hidden form.
- `/system [network|info]` -- bare `/system` shows connection + registry
  status; `/system network` shells out to `nmcli device status` (real
  command, not a fake status page); `/system info` reads
  `/etc/os-release` + `platform.uname()`. Actually *changing* network
  config (the literal "네트워크 드라이버 설정" ask) isn't implemented --
  documented here as a real, honest gap rather than faked, same as every
  other "not yet" in this project. `/system` is a small, extensible
  command group specifically so config-changing subcommands can be added
  later without another redesign.
- `/cli` -- spawns `foot` directly (`subprocess.Popen`, not blocking the
  HTTP response). `system_files/etc/sway/config` gained back a
  `for_window [app_id="foot"] fullscreen enable` rule (removed in the
  previous redesign since the old text shell wasn't launched this way
  anymore) so a `/cli` terminal behaves exactly like the OAuth-login
  Firefox window: takes over the screen, closing it reveals the kiosk
  page again.

**Frontend**: full rewrite of `webshell/static/`. `index.html`/
`style.css` now follow the Claude Design reference's visual language
(dark `#131314` background, `#1e1f20` elevated rounded card for the
prompt, circular accent send button) instead of the previous ad-hoc dark
theme. The old fixed-height `#stage` + fixed-bottom `#dock` layout is
gone; the page is now a normal scrollable column: prompt card, then a
"명령" tile grid (Claude/Grok/Ollama/custom-LLM/시스템 설정/CLI 터미널,
colored gradient thumbnails matching the reference's colorful cards), then
a "설치된 프로그램" tile grid for registry apps (currently always empty --
Phase 2.8 registration still doesn't exist -- but the UI slot is real and
wired to `/api/apps`, ready for when it does). `app.js`'s only
interaction primitive is `submitPrompt(text)` -- every tile's click
handler either calls it directly (built-in commands, app tiles) or
prefills the textarea for commands that need more typed detail (`/llm
custom `). No tile has its own fetch/POST call; unification is enforced
by there being nothing else to call.

One behavior change worth calling out: the prompt input is **no longer
disabled pre-connection**. It has to accept `/llm`, `/system`, `/cli`,
`/help` before any LLM exists -- disabling the whole box until connected
(the previous design) was fighting the new architecture directly. Plain-
language prompts still correctly error server-side
("LLM이 연결되지 않았습니다...") when no provider is connected; that's
enforced in `api.py`, not by disabling the input.

149 tests pass. Still fully unverified against a real boot -- same
caveat as every Phase 4 entry above.

## Live CLI activity log panel + CI auto-chains disk builds (2026-07-11)

Two independent follow-ups from the same round of feedback.

**1. Live log panel.** The redesigned shell still left the user staring
at a static "연결 중..." message with zero visibility into what was
actually happening underneath -- exactly the same class of problem as
the earlier black-screen and silent-thread bugs, just one layer up (the
*mechanism* now correctly reaches the user, but there's nothing to show
between "started" and "finished/failed" for a slow operation). Explicit
request: a real-time log window, right side of the screen, showing what
the CLI is actually doing.

Implementation: `webshell/logbuf.py`'s `LogBuffer` is a thread-safe ring
buffer (`collections.deque` + `threading.Condition`). `GET /api/logs?after=<id>`
long-polls against it -- blocks up to 20s until a new entry exists, then
returns immediately; the frontend just re-issues the request the instant
a response comes back, giving near-real-time updates over plain HTTP
with no websocket. Every layer that shells out to a real CLI now accepts
an optional `log: Callable[[str], None]`, threaded all the way down:
`server.py` → `api.prompt_payload()` → `commands.dispatch()` →
`connect.run_connect()`/`run_connect_token()` → `onboarding.py`'s
`connect_*()` functions → `providers/cli_subprocess.py` and
`providers/local_ollama.py`, which log the actual install command,
its exit code, the login subprocess starting and finishing, and the
Ollama pull's start/success/failure. Default is a no-op everywhere, so
every existing caller (`onboarding_cli.py`, all prior tests) is
unaffected. `commands.dispatch()` also logs the raw command text itself
on every call, so `/system network`'s `nmcli` invocation, `/cli`'s
terminal spawn, and even plain `/help` all show up.

Frontend: `#layout` is now a flex row -- `#page` (the existing prompt +
tiles column) on the left, a fixed-width `#log-panel` (dark terminal-like
background, monospace, auto-scrolling) on the right. `pollLogs()` in
`app.js` is the long-poll loop.

**2. CI: disk builds now chain automatically.** `build-disk.yml` only had
`workflow_dispatch` (manual) and a narrow `pull_request` trigger --
getting an actual disk image after a push to `main` required manually
running it. Added a `workflow_run` trigger keyed off `build.yml`'s exact
name ("Build container image"), gated on `conclusion == 'success'` so a
failed container build doesn't waste a disk build on a stale/nonexistent
image. Since a `workflow_run`-triggered run has no manual `platform`
input, the job now computes its platform matrix dynamically (a small
`determine-platforms` job): `workflow_dispatch` still builds exactly the
one platform picked from the dropdown; every other trigger (the new
automatic chain, and the existing `pull_request` trigger) builds both
amd64 and arm64, matching `build.yml`'s own matrix. Every `inputs.platform`
reference in the job became `matrix.platform`.

162 tests pass. The log panel is logic-tested (LogBuffer directly, log
lines asserted from `commands.dispatch()`/`cli_subprocess.py`/
`local_ollama.py`) but has never rendered on a real screen. The CI change
can't be exercised at all until this branch is merged to `main` --
`workflow_run` triggers only fire for workflow files present on the
default branch.

## npm install timeout too short -- confirmed via the new log panel (2026-07-11)

First real payoff from the log panel added earlier today: the user's
screenshot showed the exact failure for the first time, instead of a
guess --

```
[cmd] /llm claude
[llm] claude 연결 시작
[claude] 설치 중: npm install -g @anthropic-ai/claude-code
[llm] claude 연결 중 예상치 못한 오류: TimeoutExpired: Command
  '['npm', 'install', '-g', '@anthropic-ai/claude-code']' timed out
  after 120 seconds
```

`CliSubprocessProvider._default_run()` used a single hardcoded 120s
`subprocess.run(..., timeout=...)` for every call it makes -- both the
package install and the fast `<cli> -p ...` prompt calls. A real `npm
install -g` (registry resolution, download, any postinstall steps) on a
VM sharing virtio-net bandwidth with the host routinely needs more than
two minutes; 120s was simply too tight.

**Fix**: split the timeout by call type instead of raising one global
number blindly. `_default_run()` now picks `_INSTALL_TIMEOUT_SECONDS =
600` when the argv matches `self.install_argv`, else
`_PROMPT_TIMEOUT_SECONDS = 120` (unchanged -- a real completion call
should still fail fast if something's actually hung, not block the
whole connect flow for 10 minutes). 600s matches `interactive_login()`'s
existing timeout for the login subprocess, so the two genuinely
long-running operations are now consistent.

Worth noting for what this round validates: the catch-all `except
Exception` added in `connect.py` after the earlier "연결 중..." forever
bug did exactly its job here -- `TimeoutExpired` isn't
`ExternalLoginRequired`/`ProviderNotReady`, but it still reached the
user as a clear, readable message instead of vanishing. Combined with
the log panel, this is the first Phase 4 failure in this project that
got diagnosed from real evidence on the first try, not a hypothesis.

164 tests pass, including two asserting `_default_run` picks the right
timeout for install vs. prompt calls.

## npm install exit 254 -- likely EACCES, not a missing driver (2026-07-11)

User's follow-up question, after a second log-panel screenshot showed a
new failure past the timeout fix:

```
[claude] 설치 중: npm install -g @anthropic-ai/claude-code
[claude] 설치 실패 (종료 코드 254)
[claude] 실행: claude login (브라우저가 열리면 로그인을 완료하세요)
[llm] claude 연결 중 예상치 못한 오류: FileNotFoundError: ... 'claude'
```

User asked whether basic devices (network/graphics/sound) are actually
working out of the box on this image. Short answer: almost certainly
yes for the *driver* layer -- `virtio-net`/`virtio-gpu`/`virtio-snd` are
built into the stock Fedora kernel this image ships (no separate driver
package needed for a QEMU/UTM VM), and NetworkManager auto-configures a
detected ethernet device via DHCP by default. The failure here doesn't
match a missing-driver signature.

**Two separate bugs, actually**:

1. **The real cause of exit 254, by far the more likely explanation
   given how the image is built**: `npm install -g` was being run at
   *first connect*, as the unprivileged `aios` kiosk user. npm's default
   global install prefix (targeting `/usr/lib/node_modules` for a
   system-installed Node.js) is root-owned; a non-root global install
   there fails with `EACCES`, and npm has been known to surface that as
   a non-1 exit code depending on version -- 254 is consistent with
   that, though the previous fix (this same commit) didn't preserve
   stderr to confirm it outright, only the exit code. **Not deeply
   confirmed** (no stderr captured from that attempt), but far more
   likely than a driver/network problem given `aios` has no elevated
   permissions anywhere in this image.
2. **A real bug independent of #1**: once the install step failed and
   raised `ExternalLoginRequired`, `connect_claude_via_browser()` still
   blindly went on to call `interactive_login()` (`claude login`) --
   which, since `claude` was never actually installed, raised a second,
   unrelated `FileNotFoundError` instead of surfacing the original
   install failure. This masked the real problem behind a confusing
   secondary error.

**Fixes**:
- `build.sh` now runs `npm install -g @anthropic-ai/claude-code
  @xai-official/grok` at **build time**, as root, right after installing
  `nodejs`. This is the actual structural fix: no more first-boot
  network dependency, no more permission mismatch, no more multi-minute
  wait in the connect flow -- `ensure_ready()`'s binary-presence check
  finds both CLIs already on PATH and skips the runtime install entirely.
  Runtime `npm install -g` as `aios` still exists as a fallback for
  providers this image doesn't know to bake in ahead of time (the
  `/llm custom` path) -- so the underlying permission risk isn't fully
  gone for that path, just no longer hit by the two built-in providers.
- `onboarding.py`'s `connect_claude_via_browser()`/`connect_grok()`/
  `connect_custom()` now check `provider.status()` after catching
  `ExternalLoginRequired`: if it's `ProviderStatus.ERROR` (binary not
  present), they re-raise immediately instead of attempting
  `interactive_login()` against a binary that was never installed. Fixes
  bug 2 for any future install failure, not just this one.
- `cli_subprocess.py`'s install-failure log line now includes a stderr
  snippet (previously exit-code-only), so the *next* install failure --
  whether this one recurs against the baked-in CLIs' fallback path, or a
  `/llm custom` provider hits it -- shows the actual npm error instead
  of requiring another guess.

**Practical next step suggested to the user**: once rebuilt, `/system
network` (already implemented, runs real `nmcli device status`) is the
direct way to confirm the network device itself is actually up, if
connectivity is ever in question again.

167 tests pass, including new coverage for the status()-gated
interactive_login() short-circuit across all three connect_* functions.

## Image build fails: `npm install -g` at build time hits `/root` ENOTDIR (2026-07-11)

The previous fix (baking Claude/Grok CLIs in at build time) broke the
CI build itself:

```
+ npm install -g @anthropic-ai/claude-code @xai-official/grok
npm error code ENOTDIR
npm error syscall mkdir
npm error path /root
npm error errno ENOTDIR
npm error Invalid response body while trying to fetch
  https://registry.npmjs.org/@anthropic-ai%2fclaude-code:
  ENOTDIR: not a directory, mkdir '/root'
```

Same root cause pattern as the `/opt` and `aios` home-directory issues
already documented above, just hitting `root`'s account this time
instead of `aios`'s: this base image's `/root` is (like `/home`, `/opt`)
an ostree symlink into `/var` (`-> var/roothome`), and `/var` isn't
populated the way a real booted system's is during `podman build` --
`/var/roothome` doesn't exist as an actual directory in this build
stage, so `/root` resolves to something `mkdir` can't create a `.npm`
cache directory under (`ENOTDIR`). npm needs a writable `$HOME` to
resolve its cache location before it can even reach the registry, so
this failed before making any real network request.

**Fix**: `HOME=/tmp npm install -g ...` -- `/tmp` is already a real,
writable `tmpfs` in this build step (the Containerfile's own
`--mount=type=tmpfs,dst=/tmp`), so pointing npm's `$HOME` there for just
this one command sidesteps the problem entirely. Nothing at runtime
depends on root's home directory state either way -- `aios`, not root,
is the account the shipped image actually boots into.

Not yet re-verified in CI (this fix hasn't been through a build run
yet) -- next push should confirm whether this clears the `npm install`
step, and then (assuming it does) finally let the actual "click Claude,
already-installed, straight to login" flow get boot-tested for the
first time.

## `claude login` exits non-zero with zero visible output (2026-07-11)

Fourth log-panel screenshot in this same debugging chain, and genuine
further progress -- the npm-at-build-time fix worked (`claude`
resolved on PATH immediately, no install step at all this time):

```
[cmd] /llm claude
[llm] claude 연결 시작
[claude] 로그인 상태 확인 중...
[claude] 로그인 필요 (확인 실패: )
[claude] 실행: claude login (브라우저가 열리면 로그인을 완료하세요)
[claude] claude login 종료 (코드 1)
[llm] claude 연결 실패: anthropic-claude-code: run `claude login` first.
  `claude login` exited non-zero
```

`claude login` itself failed, but with **no output at all** to go on --
`interactive_login()` ran the login command with real inherited stdio
(uncaptured), on the theory that a human would be watching a real
terminal. That premise no longer holds for the GUI shell: sway's `exec`
redirects `webshell_cli`'s entire stdio to a log file
(`~/.local/share/oais/shell.log`) that nothing in the UI surfaces, so
`claude login`'s own stdout/stderr -- whatever URL or error it printed
-- went straight into a file nobody was reading. The log panel only ever
had the exit code to show.

**Fix 1 -- capture and stream, not just start/end markers.**
`interactive_login()` now runs the login command via `Popen` with
`stdout=PIPE, stderr=STDOUT`, pumping each output line into both
`_log()` (so it reaches the visible log panel line by line, in near
real time) and `print()` (so `onboarding_cli.py`'s real-terminal
fallback -- which still runs inside an actual visible `foot` window --
keeps seeing it live too, same as before). This isn't just a diagnostic
nicety: it's the only way a Grok-style device-code URL+code ever reaches
the user in the GUI shell at all, since that flow has no browser
auto-launch to fall back on.

**Fix 2 -- a concrete, likely cause for the failure itself.** This image
never installed `xdg-utils` or registered a default browser. A bare
`sway` session provides no desktop environment to do either
automatically (unlike GNOME/KDE), so `claude login`'s attempt to
auto-open a browser (however it does that internally -- most Node CLIs
either shell out to `xdg-open` or use a package that falls back to it)
plausibly had nothing to open anything with, and exited non-zero as a
result. Added `xdg-utils` to the package list, `/etc/xdg/mimeapps.list`
registering `firefox.desktop` as the default handler for
http/https/text-html (the standard freedesktop.org association file
`xdg-open` reads), and `BROWSER=firefox` in `/etc/environment` (applied
to every login session via PAM's `pam_env`, including the kiosk
autologin) as a second, more direct signal for tools that check it
before falling back to `xdg-open`.

**Not confirmed** -- this session still has no way to capture the actual
`claude login` output that was silently discarded before fix 1 shipped,
so fix 2's browser-registration diagnosis is the most plausible
explanation given how this image is built, not a certainty. The next
attempt should have real output in the log panel either way, which
turns any remaining failure into a real diagnosis instead of another
guess.

168 tests pass.

## The actual root cause: `claude login` isn't a real subcommand (2026-07-11)

The streaming fix from the previous entry immediately paid off -- the
next log-panel screenshot showed the real output for the first time:

```
[claude] 실행: claude login (브라우저가 열리면 로그인을 완료하세요)
[claude] Not logged in · Please run /login
[claude] claude login 종료 (코드 1)
```

`"Not logged in · Please run /login"` -- the leading slash is the
giveaway. Verified directly against the real `claude` CLI installed in
this dev sandbox (`claude --help`, `claude auth --help`, read-only,
no auth state touched): **there is no top-level `login` subcommand at
all**. The real commands are `claude auth login` / `claude auth logout`
/ `claude auth status` (under an `auth` command group) and
`claude setup-token`. `login_command = "claude login"` in
`providers/claude_cli.py` was simply wrong from the start -- running it
gets parsed as a normal prompt/REPL invocation, which (no TTY, piped
stdio) can't start a REPL and just prints that hint before exiting 1.

This was never a windowing/multi-window-management problem, despite a
reasonable-looking symptom (user's hypothesis, given every window in
this kiosk sway config gets forced fullscreen -- a new window and "the
screen just changed" look identical from the outside). sway manages
multiple windows fine; the login command was failing before a browser
window would ever have been relevant.

**Fix**: `ClaudeCliProvider.login_command = "claude auth login"`.
Updated all prose elsewhere (onboarding.py, cli.py, README.md) that
described the old (wrong) command as correct.

**Still open, flagged for the next round rather than guessed at now**:
once `claude auth login` actually runs, does its browser-open attempt
produce a genuinely new, visible window, or does it hand off to the
*already-running* kiosk Firefox instance and open as a background tab
that kiosk mode's chrome-less UI gives no way to reach? `--kiosk`
enables single-instance remoting like any other Firefox launch, so this
is a real possible follow-up failure mode -- just not one there's
evidence for yet. If the next attempt shows `claude auth login` running
successfully but no visible browser ever appears, that's the next thing
to fix (likely: a separate Firefox profile for kiosk-vs-external-URL
launches, so they can never remote into each other).

168 tests pass, including the corrected `login_command` assertion.

## Login succeeded, but stuck on the OAuth success page with no way back (2026-07-11)

Real progress -- Claude's own "Build something great / You're all set
up for Claude Code. You can now close this window." success page
appeared, confirming `claude auth login` completed. But the user then
had no way to actually get back to the AI-OS shell: that Firefox window
has no title bar, no close button, no chrome at all (this kiosk's sway
config never had any), and there was no keybinding to close a window
either -- `system_files/etc/sway/config`'s own comment claimed "closing
it returns focus to the kiosk window underneath," but nothing actually
made that true. sway itself manages multiple windows fine; there was
just no way to act on one.

**Fix, two parts**:
1. `webshell/wm.py` (new): snapshots sway's Firefox window IDs (via
   `swaymsg -t get_tree`) before a login flow's connector call and
   again after, then closes (`swaymsg [con_id=N] kill`) whatever's new
   -- i.e. whatever window that flow opened. Wired into
   `connect.py:run_connect()` around the connector call (`try/finally`,
   so it fires on success *and* failure -- an error page left open would
   block the kiosk exactly the same way). Best-effort throughout: no
   swaymsg binary, not running under sway (tests, `onboarding_cli.py`'s
   headless path), malformed IPC output -- all just skip silently,
   never fail the connection attempt over a window-management nicety.
2. `system_files/etc/sway/config`: added `bindsym Mod1+F4 kill` as a
   manual fallback for anything wm.py's automatic close doesn't catch.
   Alt+F4 specifically because it's universal enough to not depend on a
   Super/Mod key a given keyboard/VM might not forward.

178 tests pass, including a full `run_connect()` integration test
confirming the close call fires with the right window ID.

## Still stuck on the OAuth success page after the wm.py fix -- reused tab, not a new window (2026-07-13)

This is exactly the failure mode flagged as "still open" at the end of
the previous entry. A new screenshot showed the same symptom as before
(Claude's "Build something great... you can now close this window"
page, filling the whole screen, no way back) *after* `webshell/wm.py`
had already shipped -- so the fix from 2026-07-11 evidently didn't
fire. The user also independently pushed back on the underlying design:
even a chromeless kiosk needs *some* real way to move between windows
(browser popup, a spawned `/cli` terminal), not just an auto-kill that
either works silently or leaves you stuck with zero recourse.

**Root cause (plausible, not directly confirmed -- this dev sandbox has
no display to boot-test against, same caveat as the rest of Phase 4's
window-management work)**: the kiosk's own desktop *is* a Firefox
`--kiosk` window (`webshell_cli.py`), already running by the time a
login flow tries to open its OAuth URL. Firefox is single-instance by
default -- a second `firefox <url>` invocation (which is what a bare
`firefox.desktop` xdg entry, or `xdg-open`, or Node's `open` package via
`$BROWSER`, all resolve to) gets sent to the *already-running* kiosk
instance over Firefox's remoting protocol and opens as a new **tab** in
the **same window**, not a separate one. Kiosk mode hides all chrome
(no tab bar, no back button), so that tab's content -- the OAuth success
page -- just permanently overwrites the kiosk UI. Critically, this also
explains why `wm.py`'s fix didn't help: its `swaymsg -t get_tree` diff
looks for a *new* sway con_id, and there never was one -- it's the same
window, same con_id, just navigated to a different URL. There was
nothing for it to find and close.

**Fix, two parts** (matches the user's own framing: a real fix for this
specific bug, plus a general desktop primitive so this class of problem
degrades gracefully next time):
1. `system_files/usr/local/bin/oais-open-browser` (new): a wrapper
   script that runs `firefox --new-window "$@"` instead of a bare
   `firefox`. `--new-window` forces Firefox's remoting to open a
   genuinely separate top-level window instead of reusing a tab, which
   is what `wm.py`'s existing diff-and-kill logic actually needs to find
   something to act on. Registered as the default handler for
   `text/html`/`x-scheme-handler/http(s)` etc. via a new
   `system_files/usr/share/applications/oais-browser.desktop` (replacing
   the previous direct `firefox.desktop` mapping in
   `/etc/xdg/mimeapps.list`), and as `$BROWSER` in `/etc/environment`
   (`build_files/build.sh`).
2. `system_files/etc/sway/config`: added real focus-cycling keybindings
   -- `Mod1+Tab`/`Mod1+Shift+Tab` (sway's built-in `focus next`/
   `focus prev` sibling cycling) alongside the existing `Mod1+F4 kill`.
   This is the "기본적인 GUI 구성 요소" the user asked for directly: even
   though there's still no visible chrome (no taskbar, no window list),
   a human can now alt-tab between whatever's actually open -- the kiosk
   shell, a login popup, a `/cli` terminal -- instead of depending
   entirely on `wm.py` guessing right.

**Still not independently confirmed**: whether `--new-window` sent to a
running `--kiosk` instance reliably produces a window that both (a) gets
its own distinct sway con_id and (b) doesn't inherit kiosk-mode
chromelessness in a way that breaks something else. This needs a real
boot test to fully verify, like the rest of this phase's window-
management work; flagging it explicitly rather than claiming certainty
the codebase alone can't provide.


## Grok Bot OS로 전환 (2026-10-18)

제품 목표가 바뀌었다. 설치하고 켜면 화면에 Grok Bot만 있고, 로그인과 구독은 Grok Bot 계정이 하며, 필요한 앱은 Grok Bot이 이 PC에 설치한다. 예전의 자체 오케스트레이터(상태 머신, 태그 레지스트리, Claude/Grok/Ollama CLI 추상화, 개발 에이전트, 슬래시 명령 웹 셸)는 그 자리를 Grok Bot이 대신하므로 부팅 경로에서 뺐다.

### 이미지에서 뺀 것

`orchestrator/` 전체를 `legacy/orchestrator/`로 옮겼다. 삭제는 하지 않았다. 검은 화면, `claude login`이 없는 서브커맨드라는 사실, Firefox 키오스크가 OAuth 페이지를 같은 창 탭으로 흡수한 문제의 원인 코드가 거기 있다. Containerfile은 이 디렉터리를 복사하지 않고, sway도 실행하지 않는다. `check` 워크플로는 그 파이썬 테스트를 돌리지 않는다.

같이 뺀 것:

- 이미지에 굽던 `nodejs`와 `npm install -g` Claude/Grok CLI. 빌드 중 `/root` ENOTDIR 우회(`HOME=/tmp`)도 따라서 필요 없어졌다. `/root`가 ostree 심볼릭 링크라 빌드 중 `$HOME`으로 쓰면 안 된다는 사실은 그대로 유효하다.
- `foot`. 예전의 텍스트 셸과 `/cli`용이다. 복구 콘솔은 `Ctrl+Alt+F2`의 getty다.
- 키오스크 계정 `aios`. 새 계정은 `grokbot`이다. 비밀번호는 잠그고 tty1 자동 로그인만 연다.
- 자체 계정, `~/.config/oais/provider.json`, OAuth 디바이스 플로, API 키 저장.

### 남긴 것

부팅과 이미지 파이프라인은 유지한다.

- 베이스 `quay.io/fedora/fedora-bootc`. `ID=fedora`는 바꾸지 않는다.
- GHCR 이름 `ghcr.io/head77x/oais`와 `ghcr.io/head77x/oais-arm64`. 매니페스트 리스트로 합치지 않는다.
- `build.yml`, `build-disk.yml`의 구조. `workflow_run`으로 디스크 빌드를 잇는 것, root `podman login`, `--rootfs ext4`, ISO kickstart의 `ghcr.io/head77x/oais:latest`를 sed로 바꾸는 것, Anaconda Users 모듈을 끄지 않는 것.
- S3 접두사 `oais/`와 아티팩트 이름. 받아 가던 경로다.
- `/usr`와 `/etc`에만 부팅에 필요한 파일을 둔다. 빌드 중 `/var`에 쓴 홈은 이미지에 안 남을 수 있다.
- tmpfiles로 `/var/home/<키오스크계정>`을 매 부팅 만들고, 들어 있는 파일은 지우지 않는다. 계정 이름만 `grokbot`으로 바꿨다.
- sway 키오스크. 패널 없음, 테두리 없음, `Alt+Tab`, `Alt+Shift+Tab`, `Alt+F4`.
- 기본 브라우저는 키오스크 Firefox와 다른 프로필의 `--new-window` 래퍼(`grokbot-open-browser`)다. 2026-07-13에 같은 창 탭으로 흡수되던 문제를 피하기 위한 것이다. 키오스크 Firefox에는 `--no-remote`와 전용 프로필을 추가로 줬다.
- CJK 폰트, `xdg-utils`, `podman.socket`, `tmux`, `htop`.

### sway를 유지한 이유

cage는 앱 하나를 전체화면으로 띄우고 끝나면 다시 실행해서 더 작아 보인다. 이 제품은 Grok Bot과 설치한 앱을 오가야 한다. cage는 창을 여러 개 다루지 못한다. sway는 UTM에서 tty1 자동 로그인 뒤 실제로 뜬 컴포지터이고, Alt+Tab / Alt+F4 수정도 sway 설정이다. 재시작은 `grokbot-kiosk`의 루프 10줄로 처리한다. cage로 바꿔 그 실기 수정을 버릴 이유가 없다.

Plymouth는 넣지 않았다. 부팅 스플래시는 아직 확인할 수 없고, 첫 화면 목표와 무관하다.

### 플레이스홀더

Grok Bot Linux 빌드는 이 저장소에 없고, 공개 URL도 확인하지 못했다. 바이너리를 만들어 넣지 않는다. 페이로드와 sha256이 없으면 `grokbot-launch`는 Firefox 키오스크로 로컬 안내 페이지를 연다. `GROKBOT_WEB_URL`이 있으면 그 주소를 연다. 페이로드가 있으면 같은 `grokbot-launch`가 `/usr/lib/grokbot/grokbot-native`를 exec한다. 종류와 체크섬 규칙은 `docs/GROKBOT_APP.md`.

그래서 이 문단이 적힌 커밋의 첫 화면은 Grok Bot 로그인이 아니었다. 안내 페이지였다. 그 다음 커밋에서 기본 빌드는 Grok Bot 0.71.2 RPM이다. 플레이스홀더는 `GROKBOT_DISABLE_BUNDLED_APP=1`일 때만 남는다. 바로 아래 항목이 그 기록이다.

### 앱 설치

사용자 권한 `grokbot-install`만 둔다. Flatpak은 `--user`와 Flathub 앱 id만. 로컬 파일은 `~/Apps`와 사용자 데스크톱 파일로 복사하고, 심볼릭 링크와 홈 밖 경로는 거부한다. 앱 실행 중 격리는 없다. Flatpak 앱만 Flatpak 샌드박스를 탄다. 로컬 앱 격리는 Phase D로 남긴다. 규격은 `docs/GROKBOT_INSTALL.md`.

### 이 항목을 쓸 때 확인하지 못한 것

이 개발 환경에는 KVM과 fedora-bootc 이미지 빌드가 없다. 셸 테스트, shellcheck, 워크플로 YAML, `just --dry-run`만 돌렸다. 새 이미지의 부팅, Firefox 키오스크 렌더링, fuzzel, Flathub 설치, SELinux enforcing에서의 실행은 실기 또는 VM이 필요하다. 2026-07-09 UTM 확인은 이 트리가 아니다.

## Grok Bot RPM을 두 아키텍처에 넣는다 (2026-10-18)

기본 이미지는 플레이스홀더가 아니다. Grok Bot 0.71.2 RPM을 amd64와 arm64 모두에 넣는다. 이미지가 Fedora bootc라 deb가 아니라 RPM이다. 플레이스홀더는 `GROKBOT_DISABLE_BUNDLED_APP=1`일 때만 남는다.

고정 URL과 sha256은 `docs/GROKBOT_APP.md`와 `build_files/install-grokbot-app.sh`에 있다. `api2.cursor.sh`의 latest 리다이렉트는 문서에만 적고 빌드는 쓰지 않는다. 다음 빌드로 바뀌면 체크섬이 달라져 빌드가 실패해야 하기 때문이다.

이 환경에서 두 RPM을 받아 sha256이 문서의 값과 같은지 확인했다. x86_64는 92776633바이트, aarch64는 87733289바이트다. `rpm -qpl`, `rpm -qp --scripts`, `rpm -qp --requires`, 데스크톱 파일, x86_64 `grok-bot`의 `readelf -d` NEEDED를 봤다. `dnf5 install`과 부팅은 하지 않았다.

### RPM이 하는 일과, 빌드가 그걸 그대로 두지 않는 이유

패키지 이름은 `grok-bot`이고 파일은 `/opt/Grok Bot/grok-bot`에 있다. 데스크톱 파일은 `/usr/share/applications/grok-bot.desktop`이고 `StartupWMClass=grok-bot`, `Exec=grok-bot %U`, `MimeType=x-scheme-handler/grokbot;x-scheme-handler/sand`다.

`%post`는 `/usr/bin/grok-bot`을 그 `/opt` 경로에 연결하고, `chrome-sandbox` 권한을 바꾸고, AppArmor 프로파일을 넣고, `/etc/yum.repos.d/grok-bot.repo`를 만든다. 셋 다 이 이미지에서 실행하면 안 된다.

- `/opt`는 이 베이스에서 `/var/opt`다. 빌드 때 `/var`에 쓴 파일은 부팅 디스크에 안 남을 수 있다.
- 경로에 공백이 있으면 Electron의 setuid `chrome-sandbox`가 동작하지 않는다. 페이로드의 `chrome-sandbox`는 `0755`였다.
- AppArmor 프로파일은 Debian 쪽 설치 단계다.
- yum 저장소를 넣으면 고정해 둔 RPM이 아니라 그 저장소의 다음 빌드를 받게 된다. 업데이트는 이미지를 다시 만들어 `bootc upgrade`하는 쪽이다.

그래서 `dnf5 install --setopt=tsflags=noscripts`로 의존성만 받고, 트리를 `/usr/lib/grokbot/app`으로 옮긴 뒤 `chrome-sandbox`를 `4755`로 둔다. `/usr/bin/grok-bot`은 심볼릭 링크가 아니라 Wayland 래퍼다. `--ozone-platform=wayland`와 `--enable-features=UseOzonePlatform`을 붙인다. `--no-sandbox`는 넣지 않는다. 샌드박스가 SELinux에서 되는지는 부팅해서 봐야 한다.

`rpm -V grok-bot`은 파일이 옮겨져서 어긋난다. 앱 업데이트는 그 rpm을 시스템 안에서 올리는 방식이 아니다.

`Requires`는 `gtk3`, `nss`, `at-spi2-core`, `libnotify`, `xdg-utils`, `(libXtst or libXtst6)`, `(libuuid or libuuid1)`이다. NEEDED에는 그 밖에 cups, gbm, alsa, xkbcommon, Xcomposite 등이 있다. Fedora 패키지 이름을 `build.sh`에 적었다. 이름이 틀리면 이미지 빌드가 실패한다. 여기서는 그 dnf 설치를 실행하지 않았다.

### 창

`GROKBOT_APP_ID=grok-bot`이다. `Super+G` / `Alt+G`는 그 `app_id`에 포커스한다. Wayland `app_id`가 데스크톱 파일과 같은지는 미확인이다. `http`/`https`는 계속 `grokbot-open-browser`(별도 Firefox 프로필, `--new-window`)다. `grokbot://`와 `sand://`는 `grok-bot.desktop`이다. 예전의 `wm.py`가 OAuth 창을 자동으로 닫던 코드는 `legacy/`에만 있다. 닫기는 `Alt+F4`, 복귀는 `Alt+G`다.

## 베이스는 Fedora bootc (2026-10-18)

Arch로 바꾸지 않는다. 이미지 빌드, GHCR 이름, 디스크 설치, 실패 시 이전 배포로 돌아가는 경로가 bootc에 있다. Grok Bot이 하드웨어를 고치려고 로컬 이미지를 만드는 설계도 지금 부팅 중인 bootc 이미지를 `FROM`으로 삼는다. 그 흐름은 구현하지 않았다. 설계만 `docs/HARDWARE.md`와 로드맵 Phase G에 있다.

같은 이유로 공장 초기화의 첫 버전도 `/usr`와 bootc 배포를 지우지 않는다. `grokbot-factory-reset`은 `--confirm RESET`일 때만 `/var/home/grokbot`의 내용을 지운다. 전체 `/var` 초기화, 첫 부팅 재실행, 새 주인 설치 모드는 아직 없다.

## 2026-10-21: image, GHCR, and S3 names renamed `oais` → `grokbotos`

The earlier "names kept on purpose" decision is reversed. `IMAGE_NAME=grokbotos`
(file renamed `oais.env` → `grokbotos.env`), GHCR `ghcr.io/head77x/grokbotos` and
`ghcr.io/head77x/grokbotos-arm64`, the ISO kickstart needle in `disk_config/iso.toml`
/ `build-disk.yml`, the S3 prefix `grokbotos/`, and artifacts `grokbotos-<type>-<arch>`.
Only `ID=fedora` in os-release stays (bootc and package tooling read it).
Mentions of `oais` above are history and were left as written. Existing installs
migrate with `sudo bootc switch ghcr.io/head77x/grokbotos:latest` (arm64: `-arm64`).

## 2026-10-22 업데이트 서명 정책 (보안 리뷰 #2)

`bootc upgrade`/`switch`가 `ghcr.io/head77x/grokbotos`와 `-arm64` 이미지를 받을 때 cosign 서명을 요구한다.

- `/etc/containers/policy.json`: 두 저장소만 `sigstoreSigned`(`keyPath=/etc/pki/containers/grokbotos.pub`, `matchRepository`). 그 밖(Flatpak 런타임이 아닌 일반 컨테이너 등)은 기존 기본값 `insecureAcceptAnything` 그대로.
- `/etc/pki/containers/grokbotos.pub` = 저장소의 `cosign.pub`(테스트가 같은지 확인).
- `/etc/containers/registries.d/grokbotos.yaml`: `use-sigstore-attachments: true`(CI의 `cosign sign`이 올리는 OCI 첨부 서명).
- ISO kickstart: `--enforce-container-sigpolicy`는 넣지 않았다. VM에서 이 옵션은 정책의 default가 `insecureAcceptAnything`이면 "refusing usage"로 모든 switch를 거부했다. default를 `reject`로 바꾸면 다른 컨테이너 사용이 막히므로, 저장소별 `sigstoreSigned`만 둔다(containers/image가 pull마다 적용).

확인: 실제 GHCR `:latest`(amd64·arm64)를 이 정책으로 `skopeo copy`하면 통과, 다른 키로 바꾸면 "Source image rejected: cryptographic signature verification failed". 주의:
- 서명은 기본 브랜치 빌드에만 붙는다(PR 빌드 이미지는 서명이 없어 이 정책으로는 받을 수 없다).
- 서명 키를 바꿀 때는 새 공개키를 먼저 이미지에 넣어 배포한 뒤 키를 바꿔야 한다. 순서를 거꾸로 하면 설치된 기기가 업데이트를 받지 못한다(복구: 관리자 콘솔에서 `/etc/containers/policy.json` 수정).

## 2026-10-22 legacy/orchestrator 삭제, 베이스 이미지 다이제스트 고정 (보안 리뷰)

보안 리뷰(커밋 6f4d32f)의 L 항목: `legacy/orchestrator/webshell/server.py`의 `/api/prompt`는 인증과 Origin 검사가 없어서, 아무 웹사이트나 명령을 실행시킬 수 있었다(고정 포트 8765). 이미지에는 들어가지 않았지만 되살릴 계획이 없으므로 저장소에서 지웠다. 필요하면 git 기록에서 찾는다. `test-contracts.sh`는 그 디렉터리가 돌아오면 실패한다.

항목 #8: `Containerfile`의 `fedora-bootc`와 `grokbotos.env`의 `BIB_IMAGE`를 다이제스트로 고정했다(태그는 주석과 `:latest@sha256:` 형태로 남김). 업데이트는 다이제스트를 바꾸는 커밋으로만 한다. `.github/workflows/build-disk.yml`의 `BIB_IMAGE`와 `check.yml`의 `permissions:`는 규칙상 이 PR에서 고치지 않았다.
