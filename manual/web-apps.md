# 웹 앱 / Web apps

웹 앱을 설치하면 실행기와 독에 나타나고(바탕화면에는 두지 않는다), 자기 창에서 열리며, 데이터를 앱별로 오프라인에도 보관한다. OS 기능(소리, 네트워크, 배터리 등)은 기능별로 처음 쓸 때 확인 창으로 묻는다.

Installed web apps show in the launcher and the dock (never on the desktop), open in their own window and keep their data offline, per app. Each OS function (sound, network, battery, ...) is asked for separately, the first time the app uses it.

## 설치 / Install

- **설정 > 앱 / Settings > Apps**: `https://` 주소, 또는 `manifest.json`이 든 폴더나 `.zip` 경로를 넣고 **설치** / enter a `https://` address or a folder / `.zip` path with `manifest.json` and press **Install**.
- 터미널 / terminal:

```
grokbot-os apps                          # 목록 / list
grokbot-os apps install https://example.com/
grokbot-os apps install ~/my-app.zip [id]
grokbot-os apps launch my-app
grokbot-os apps uninstall my-app [--keep-data]
```

설치와 제거는 언제나 확인 창이 뜬다. 창에는 앱 이름, 주소(origin), 앱이 요청할 기능이 나온다. 설치만으로는 아무 권한도 생기지 않는다.
Install and remove always show the prompt with the app's name, origin and the functions it says it will ask for. Installing grants nothing.

## 실행과 저장소 / Window and storage

앱은 브라우저 주소창과 탭이 없는 자기 창(Firefox, 앱별 프로필)에서 열린다. 앱의 서비스 워커, 캐시, IndexedDB, localStorage는 그 앱만의 것이고 다시 시작해도 남는다. 제거하면 함께 지워진다(`--keep-data`로 보관 가능).
An app opens in its own window without tabs or address bar (Firefox, one profile per app). Its service worker, cache, IndexedDB and localStorage belong to that app only and survive restarts; removing the app deletes them unless `--keep-data`.

## 권한 / Permissions

앱이 기능을 쓰려 하면 확인 창이 뜬다: **항상 허용**, **한 번 허용**, **거부**. 바꾸거나 취소하려면 **설정 > 권한**. 카메라, 마이크, 전원은 매번 묻는다.
When an app wants a function, the prompt asks: **Always allow**, **Allow once**, **Deny**. Change or revoke in **Settings > Permissions**. Camera, microphone and power always ask.

## 시스템 모니터 / System Monitor

기본으로 설치되어 있다. CPU, 메모리, 디스크, 배터리, 네트워크, OS API 기록 요약을 보여 준다. 처음 열면 시스템 정보, 전원, 네트워크, 감사 기록 권한을 하나씩 묻는다. 최근 1시간 CPU·메모리 기록은 앱 저장소에 남아 오프라인에서도 보인다.
Installed by default: CPU, memory, disk, battery, network and an OS API audit summary. On first open it asks for system information, power, network and the audit log, one at a time. The last hour of CPU/memory history stays in the app's storage and shows offline too.

## 기본 앱: 파일, 메모, 미디어 플레이어 / Built-in apps: Files, Notes, Media Player

- **파일 / Files** — 홈 폴더(~)만 보입니다. 숨김 파일(.config, .ssh 등)은 권한이 있어도 보이지 않습니다. 처음에 "홈 폴더 파일 보기"를 묻고, 저장·이름 바꾸기·휴지통은 따로 "홈 폴더 파일 바꾸기"를 묻습니다. 지운 파일은 휴지통(~/.local/share/Trash)으로 갑니다. Only your home folder, never hidden files; seeing and changing are separate permissions; deleting moves to the trash.
- **메모 / Notes** — OS 권한이 필요 없습니다. 메모는 이 앱 전용 저장소에만 있고 인터넷 없이도 됩니다. Needs no permission; notes stay in the app's own storage and work offline.
- **미디어 플레이어 / Media Player** — 고르거나 끌어다 놓은 음악·동영상을 재생합니다(파일은 컴퓨터 밖으로 나가지 않습니다). "미디어 키" 권한을 주면 키보드의 재생/다음/이전 키로 조작할 수 있습니다. Plays files you pick; with the "Media keys" permission it takes the keyboard media keys.

## 앱 만들기 / Making an app

`manifest.json`(W3C 웹 앱 매니페스트)에 선택 항목 `"grokbot": {"id": "my-app", "name_ko": "내 앱", "scopes": ["audio"]}`를 넣는다. 앱은 같은 origin의 `POST /v1/rpc`로 OS API를 부른다(`docs/OS_API.md`). 인라인 스크립트와 인라인 style 속성은 CSP로 막혀 있다.
Add an optional `"grokbot": {"id": "my-app", "name_ko": "내 앱", "scopes": ["audio"]}` member to a W3C `manifest.json`. The app calls the OS API with `POST /v1/rpc` on its own origin (`docs/OS_API.md`). Inline scripts and inline style attributes are blocked by the CSP.
