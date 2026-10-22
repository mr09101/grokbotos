# 보안 정책 / Security Policy

## 지원 버전 / Supported versions

| 버전 / Version | 지원 / Supported |
|---|---|
| `main` 브랜치와 최신 이미지 (`ghcr.io/head77x/grokbotos:latest`, `ghcr.io/head77x/grokbotos-arm64:latest`) / `main` and the latest images | ✅ |
| 그 밖의 브랜치, 태그, 예전 이미지 / other branches, tags, older images | ❌ |

보안 수정은 `main`에만 들어가고 다음 이미지 빌드로 배포된다. 설치된 시스템은 `sudo bootc upgrade`로 받는다.
Fixes land on `main` and ship with the next image build. Installed systems pick them up with `sudo bootc upgrade`.

## 권한 모델과 위협 모델 / Permission and threat model

외부 검토자(사람, Claude, Astra 등)가 감사할 수 있도록 grokbotd 권한 모델을 한곳에 적는다. 구현은 `system_files/usr/lib/grokbot/grokbotd/` (`perms.py`, `rpc.py`, `consent.py`, `server.py`), 시험은 `tests/grokbotd/test_consent.py`다. 상세 규칙은 [`docs/OS_API.md`](docs/OS_API.md#permission-model).
This section states the grokbotd permission model in one place so external reviewers (people, Claude, Astra, …) can audit it. Code: `grokbotd/perms.py`, `rpc.py`, `consent.py`, `server.py`; tests: `tests/grokbotd/test_consent.py`; full rules: [`docs/OS_API.md`](docs/OS_API.md#permission-model).

### 모델 / Model

- **권한 단위는 OS 기능(scope)이다. 앱 단위가 아니다.** / **Permissions are per OS function (scope), not per app.** Scopes: `system`, `windows`, `desktop`, `apps`, `display`, `audio`, `network`, `power`, `input`, `notifications`, `lock`, `screen`, `files`, `camera`, `microphone`, `location`, `permissions`, `audit`. 메서드마다 scope 하나와 접근(read/write)이 스키마에 고정되어 있다. / Each method has exactly one scope and an access level fixed in the schema.
- **호출자(principal)마다, scope마다 모드 하나**: `allow` / `ask` / `deny`. 설치 시 한꺼번에 주는 권한, `"*"`, 앱 전체 권한은 없다. / **One mode per caller per scope.** There is no install-time blanket grant, no `"*"` and no app-wide grant.
- **principal**: `local:uid=N:unit=<systemd unit>` 또는 `local:uid=N:exe=<실행 파일>[:script=<스크립트>]`(같은 사용자의 unix 소켓 프로세스. 커널의 SO_PEERCRED pid로 /proc의 cgroup·exe·cmdline을 읽어 식별, `x-client`는 표시용 이름일 뿐 / identified by the kernel via SO_PEERCRED: pid -> systemd unit, or executable and script; `x-client` is only a label. 식별 실패 시 `local:uid=N:unknown`, 저장 불가 / unidentified callers cannot store grants), `origin:<scheme://host:port>`(브라우저가 붙인 Origin), 그 밖(`http:no-origin`, `http:bad-origin`)은 아무 권한도 없다. / Anything other than the local user and a browser Origin gets nothing.
- **`ask`** = 네이티브 동의 창(GTK layer-shell, overlay layer, 키보드 독점, 기본 버튼 거부). 누가, 어떤 scope, 어떤 동작(파라미터, 비밀은 가림)을 보여 준다. 한 번 허용 / 항상 허용 / 거부. 60초 무응답·화면 없음 = 거부. / A native prompt (who, scope, action; Deny is default; 60 s timeout or no display = deny).
- **항상 묻는 것 / Always asks**: `camera`, `microphone`, `power`의 쓰기, 그리고 `power.action`, `camera.session.start`, `microphone.session.start`, `permissions.set`은 **모든 호출에서**(로컬 사용자도) 묻고 "항상 허용"이 없다. / These prompt on every call, for every caller, with no Always button.
- **권한 없는 origin은 묻지도 않고 거부**한다(프롬프트 스팸 방지). 요청은 `permissions.request`로만, scope마다 10분에 한 번. / Ungranted origins are denied without a prompt; `permissions.request` is rate-limited.
- **감사 / Audit**: 허용·거부·실패 모든 호출을 `~/.local/state/grokbot/audit.jsonl`(0600)에 남긴다. 비밀(`x-secret`)은 `***`. `audit.list`, `grokbot-os audit`, 설정 앱에서 본다. / Every call, allowed or not, is logged; secrets redacted.
- **취소 / Revoke**: `permissions.revoke`, `grokbot-os revoke`, 설정 앱 권한 페이지. / Via API, CLI or the Settings app.

### 신뢰 경계 / Trust boundaries

| 경계 / Boundary | 방어 / Defence |
|---|---|
| 웹 페이지 → API / web page → API | Origin별 scope 모드, Host 검사(DNS rebinding), `application/json` 필수(CSRF 단순 요청 차단), CORS는 권한 있는 origin에만 / per-origin scope modes, Host check, JSON-only, CORS only for granted origins |
| 다른 로컬 사용자 → API / other local user → API | unix 소켓 `SO_PEERCRED`, HTTP는 `/proc/net/tcp`로 TCP 상대 uid 확인. 다른 uid는 403 / peer uid checks on both transports |
| API → 시스템 / API → system | grokbotd는 사용자 서비스(root 아님, `NoNewPrivileges`). 전원은 `systemctl` → logind/polkit / user service, power via logind/polkit |
| 사용자 동의 / user consent | 동의 창은 grokbotd가 직접 띄우는 별도 프로세스이고, 요청 내용은 stdin JSON으로만 전달. 호출자는 창 내용을 고를 수 없고, 스스로 밝힌 이름은 "스스로 밝힌 이름"으로 표시 / the prompt is spawned by grokbotd; a client's self-reported name is labelled as such |

### 알려진 한계 / Known limitations (검토 요청 / please review)

1. **같은 사용자 = 같은 신뢰.** 로컬 호출자는 프로그램별로 구별되고(유닛 또는 실행 파일+스크립트) 권한도 그 신원에 묶인다. 하지만 같은 사용자 권한의 악성 프로세스는 다른 프로그램을 ptrace/LD_PRELOAD하거나, 허가된 스크립트를 고치거나, `~/.config/grokbot/api-grants.json`을 직접 고칠 수 있다. 정직한 프로그램끼리의 구분이지 샌드박스가 아니다. 인터프리터(python, sh, node) 아래의 신원은 스크립트 경로이므로, 사용자가 쓸 수 있는 경로의 스크립트에 준 권한은 그 파일을 고칠 수 있는 누구에게나 준 것과 같다. / Local callers are told apart per program (systemd unit, or exe + script) and grants bind to that identity, but a malicious same-uid process can ptrace/LD_PRELOAD another program, edit an allowed script, or edit the grants file. This separates honest programs; it is not a sandbox. For interpreters the identity is the script path, so a grant to a user-writable script is a grant to whoever can write it. pid는 연결 시점에 한 번 읽고 프로세스 시작 시각으로 재사용 여부를 확인한다 / the pid is read once per connection and checked against the process start time.
2. **동의 창 위조/가로채기.** 같은 세션의 Wayland 클라이언트는 비슷한 모양의 창을 그릴 수 있다. 동의 창은 overlay layer와 키보드 독점을 쓰지만, 컴포지터 차원의 신뢰 표시는 아직 없다. / Another Wayland client could draw a look-alike; there is no compositor-level trusted indicator yet.
3. **카메라·마이크는 협조형이다.** `camera.session.*`는 API 클라이언트용 사용 세션과 독 표시일 뿐, `/dev/video*`나 PipeWire 접근을 막지 않는다. 장치 수준 강제(xdg-desktop-portal, PipeWire 권한)는 다음 단계다. / Camera/microphone sessions are cooperative: they drive the prompt and the indicator but do not gate `/dev/video*` or PipeWire. Device-level enforcement (portals, PipeWire permissions) is future work.
4. **Origin은 브라우저가 보낸 것만 믿는다.** TCP 상대 프로세스가 호스트의 브라우저 실행 파일일 때만 Origin을 인정하고(Flatpak 등 샌드박스 제외), `*.app.localhost` origin은 실행기가 넣어 준 HttpOnly 쿠키 토큰도 요구한다. 같은 uid 호스트 프로세스는 키를 읽거나 브라우저를 조종할 수 있다(1번과 같은 신뢰 수준). / Origin counts only when the TCP peer is a host (unsandboxed) browser; `*.app.localhost` origins also need the launcher's HttpOnly token cookie. Same-uid host processes can still read the key or drive the browser (item 1).
5. **`*.app.localhost` 한 포트에 여러 앱.** 앱 사이 격리는 브라우저의 origin 격리에 의존한다. 각 앱의 토큰은 그 origin에만 유효하다. / Apps on `*.app.localhost:7311` rely on browser origin isolation; each app's token is bound to its origin.
6. **설치한 웹 앱.** 설치는 아무 권한도 주지 않고 확인 창을 거친다. 번들 앱은 앱마다 다른 origin과 Firefox 프로필을 쓰므로 저장소·쿠키·서비스 워커가 섞이지 않는다. URL 앱의 코드는 그 사이트가 언제든 바꿀 수 있으므로, URL 앱에 준 권한은 그 사이트 운영자에게 준 것이다. 번들 앱은 `~/.local/share/grokbot/webapps/`에 있어 같은 uid 프로세스가 고칠 수 있다(1번). / Installing grants nothing and is confirmed. Each bundle app has its own origin and Firefox profile (separate storage, cookies, service worker). A URL app's code is whatever the site serves, so a grant to it is a grant to the site operator. Bundles live in the user's home and can be edited by same-uid processes (item 1).
7. `files`, `location` scope는 예약만 되어 있고 메서드가 없다. / `files` and `location` are reserved; no methods yet.

## 무엇이 취약점인가 / What counts as a vulnerability

취약점은 **의미 있는 보안 경계를 넘는 것**이다. 버그나 하드닝 제안은 이슈나 Discussions에 올린다.
A vulnerability is something that **crosses a meaningful security boundary**. Ordinary bugs and hardening ideas go to issues or Discussions.

특히 / In particular:

- **grokbotd OS API 권한 / permissions**: 허용받지 않은 호출자·origin이 메서드를 부르거나, scope 모드·동의 창 검사를 우회하거나, 감사 로그를 피하거나 위조하는 것. / A caller or origin calling a method it was not granted, bypassing a scope-mode or consent check, or evading or forging the audit log.
- **웹 앱 origin 격리 / Web app origin isolation**: 한 웹 앱이 다른 origin의 권한, 데이터, 세션을 얻는 것, 또는 `127.0.0.1:7311`을 웹 페이지에서 악용하는 것(DNS rebinding, CSRF 등). / One web app gaining another origin's permissions, data or session, or a web page abusing `127.0.0.1:7311` (DNS rebinding, CSRF, …).
- **Grok Bot 제어 / control**: 사용자가 허락하지 않은 쪽이 Grok Bot 세션, 명령, MCP 도구를 조종하는 것. / An unauthorized party driving the Grok Bot session, its commands or its MCP tools.
- 일반 사용자에서 root로 권한 상승, 이미지·업데이트 체인(서명, `bootc upgrade`) 변조. / Privilege escalation to root, or tampering with the image or update chain (signatures, `bootc upgrade`).

취약점이 아닌 것 / Not a vulnerability: 이미 같은 권한을 가진 사용자가 자기 시스템을 바꾸는 것, 단순 크래시(경계를 넘지 않는 경우), 스캐너 결과만 있는 보고. / A user changing their own system with privileges they already have, plain crashes that cross no boundary, or bare scanner output.

## 취약점 신고 / Reporting a vulnerability

**공개 이슈, PR, 토론에 취약점을 올리지 마세요.** / **Do not open public issues, pull requests or discussions for vulnerabilities.**

신고는 **GitHub 비공개 취약점 신고로만** 받는다. 이메일 창구는 없다. / Reports are accepted **only through GitHub private vulnerability reporting**. There is no email channel.

- **Security** 탭 → **Advisories** → **Report a vulnerability**: <https://github.com/head77x/grokbotos/security/advisories/new>

다음을 적어 주세요 / Please include:

- 영향받는 구성 요소와 넘은 경계 / the affected component and the boundary crossed (예 / e.g. `grokbotd` capability, origin isolation)
- 재현 절차, 이미지 digest 또는 커밋 / steps to reproduce, the image digest or commit (`bootc status`)
- 개념 증명(최소한으로) / a minimal proof of concept
- 예상 영향과 전제 조건 / the expected impact and preconditions
- 알고 있다면 완화 방법 / a mitigation, if known

## 책임 있는 공개 / Responsible disclosure

- 수정이 배포되기 전에는 공개하지 말아 주세요. 기본 공개 시점은 신고 후 90일 또는 수정 배포 시점 중 빠른 쪽이며, 협의해 조정할 수 있다. / Please do not disclose before a fix ships. The default is 90 days after the report or when the fix ships, whichever comes first, adjustable by agreement.
- 다른 사람의 데이터나 시스템에는 접근하지 말고, 자신의 설치본에서만 시험하세요. / Test only on your own installations, never against other people's data or systems.

## 대응 목표 / Response targets

| 단계 / Step | 목표 / Target |
|---|---|
| 접수 확인 / Acknowledge | 3 영업일 / 3 business days |
| 판정(유효성, 심각도) / Triage (validity, severity) | 7일 / 7 days |
| 수정 배포 / Fix released | 심각 30일, 그 외 90일 / critical 30 days, others 90 days |

목표이지 보장은 아니다. 진행 상황은 advisory에서 알린다. / These are targets, not guarantees. Progress is posted on the advisory.

## 크레딧 / Credits

수정이 배포되면 GitHub Security Advisory를 공개하고, 원하는 신고자는 **릴리스 노트**와 아래 목록에 이름을 올린다. / When a fix ships, we publish a GitHub Security Advisory and, if the reporter wishes, credit them in the **release notes** and in the list below.

### 감사한 분들 / Hall of thanks

_(아직 없음 / none yet)_

## 범위 / Scope

대상 / In scope:

- 이 저장소의 코드와 이미지 구성. 특히 로컬 OS API(`grokbotd`: unix 소켓, `127.0.0.1:7311`, origin 권한, 감사 로그). 자세한 보안 모델은 [`docs/OS_API.md`](docs/OS_API.md)에 있다.
  / Code and image configuration in this repository, especially the local OS API (`grokbotd`). See [`docs/OS_API.md`](docs/OS_API.md) for its security model.

대상 아님 / Out of scope:

- Grok Bot 앱 자체, Fedora 패키지, Flathub 앱의 취약점. 각 업스트림에 신고하세요.
  / Vulnerabilities in the Grok Bot app itself, Fedora packages or Flathub apps. Report those upstream.
- 물리적 접근이나 이미 root를 가진 공격자를 전제로 한 문제. / Issues that require physical access or an attacker who already has root.
