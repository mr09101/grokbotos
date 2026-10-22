# 설정 / Settings

설정 앱은 독이나 런처(`Super+Space`)의 **설정** 아이콘으로 연다. 바탕화면에는 아이콘을 두지 않는다. 터미널에서는 `grokbot-settings [페이지]`로 연다.
Open the Settings app from the **Settings** icon in a dock or the launcher (`Super+Space`); there are no desktop icons. From a terminal: `grokbot-settings [page]`.

| 페이지 / Page | 할 수 있는 일 / What you can do |
|---|---|
| Wi-Fi (`wifi`) | 네트워크 검색, 비밀번호로 연결, 연결 끊기 / scan, connect with a password, disconnect |
| 소리 / Sound (`sound`) | 출력·마이크 볼륨과 음소거 / output and microphone volume, mute |
| 디스플레이 / Display (`display`) | 화면 밝기(노트북 화면) / brightness (laptop panels) |
| 알림 / Notifications (`notifications`) | 방해 금지, 현재 알림 / Do Not Disturb, current notifications |
| 잠금과 대기 / Lock & idle (`lock`) | 화면 끄기·잠금 시간, 지금 잠그기 / screen-off and lock timeouts, lock now |
| 키보드와 한글 / Keyboard & Korean (`keyboard`) | 한글 입력 켜기·끄기, 입력기 상태 / Korean input on/off, input method status |
| 앱 / Apps (`apps`) | 웹 앱 열기, 설치(URL 또는 번들), 제거 / open, install (URL or bundle) and remove web apps ([web-apps.md](web-apps.md)) |
| 권한 / Permissions (`permissions`) | 호출자별·기능별 권한 보기, 바꾸기, 취소, 카메라·마이크 사용 현황 / view, change and revoke grants per caller and function; camera and microphone in use |
| 감사 기록 / Audit log (`audit`) | 모든 OS API 호출(허용·거부·오류) / every OS API call |

화면은 한국어가 기본이고, 왼쪽 아래 버튼으로 English로 바꿀 수 있다. / Korean by default; the button at the bottom left switches to English.

독 상태 칸의 네트워크 아이콘을 누르면 Wi-Fi 페이지가, 빨간 카메라·마이크 표시를 누르면 권한 페이지가 열린다. 유선·VPN 같은 고급 설정은 여전히 `Super+N`(nmtui)에 있다.
Clicking the network status icon opens the Wi-Fi page; clicking the red camera/microphone indicator opens Permissions. Wired, VPN and other advanced network settings stay in `Super+N` (nmtui).

## 동작 방식 / How it works

- 설정 앱은 이미지 안의 정적 웹 앱(`/usr/share/grokbot/webapps/settings`)이고, grokbotd가 자기 origin `http://settings.app.localhost:7311`에서 내보낸다. 다른 앱과 똑같이 공개 OS API(`/v1/rpc`)만 쓰고, 자기 몫의 권한만 받는다(`/etc/grokbot/api-permissions.json`): Wi-Fi, 소리, 화면, 알림, 잠금, 입력, 권한, 감사 기록. 카메라, 마이크, 화면 캡처, 파일, 위치 권한은 없다. 전원 동작과 권한 바꾸기는 매번 확인 창이 뜬다.
  The app is static files in the image, served by grokbotd on its own origin. It uses only the public OS API with its own grant (Wi-Fi, sound, display, notifications, lock, input, permissions, audit; no camera, microphone, screen capture, files or location). Power actions and permission changes always show the prompt.
- 창은 이미지에 이미 있는 Firefox를 전용 프로필, 주소창·탭을 숨긴 창(userChrome.css), app_id `grokbot-settings`로 띄운 것이다. sway가 일반 창처럼 새 작업 공간에 타일로 배치하므로 독이 계속 보인다. 이미 열려 있으면 그 창으로 전환한다. 닫기: `Super+Q` 또는 `Alt+F4`.
  The window is the image's Firefox with its own profile with the tab strip and address bar hidden (userChrome.css) and app_id `grokbot-settings`, tiled by sway on a new workspace so the docks stay visible. A second launch focuses it. Close with `Super+Q` or `Alt+F4`.
