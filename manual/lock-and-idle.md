# 화면 잠금과 절전 / Screen lock & idle

## 처음 켰을 때: PIN 설정 / First boot: set a PIN

처음 로그인하면 "화면 잠금 PIN" 창이 뜬다. 6자 이상(숫자나 문자)을 두 번 입력한다. Enter만 누르면 건너뛴다.
On first login a "Screen lock PIN" window opens. Type a PIN of 6 or more characters twice. Press Enter alone to skip.

- PIN이 없으면 화면을 잠그지 않는다(풀 수 없게 되기 때문). 잠그려 하면 설정 창이 다시 뜬다. / Without a PIN the screen is never locked (you could not unlock it). Trying to lock opens the setup again.
- 바꾸기 / Change: 터미널에서 `grokbot-lock-setup` (현재 PIN 필요 / needs the current PIN).
- PIN은 어디에도 저장되지 않고, 시스템 암호 해시로만 남는다. / The PIN is stored only as the system password hash.

## 잠금 / Locking

| 언제 / When | 동작 / What happens |
|---|---|
| `Super+L`, `Alt+L` | 바로 잠금 / lock now |
| 5분 입력 없음 / 5 min idle | 화면 끄기 / screen off |
| 10분 입력 없음 / 10 min idle | 잠금 / lock |
| 덮개 닫기, 절전 / lid close, suspend | 잠근 뒤 절전 / lock, then suspend |
| 전체화면 영상 / fullscreen video | 절전·잠금 안 함 / idle is inhibited |

잠금 화면에서 PIN을 입력하고 Enter. 15분 안에 5번 틀리면 5분 동안 맞는 PIN도 받지 않는다. PIN 바꾸기도 5번 틀리면 5분(그 뒤로 두 배씩) 막힌다. / On the lock screen type the PIN and press Enter. After 5 wrong tries within 15 minutes, even the right PIN is refused for 5 minutes. Changing the PIN is likewise blocked for 5 minutes (doubling after that) after 5 wrong current PINs.

## 잠금이 막지 못하는 것 / What the lock does not protect against

잠금은 켜져 있는 세션만 지킨다. 키오스크 계정은 자동 로그인이라, 기기를 손에 넣은 사람이 전원 버튼으로 다시 시작하면 **PIN 없이 세션이 열린다**. 디스크도 암호화되어 있지 않을 수 있다. 기기를 두고 자리를 비울 때는 물리적으로 지키고, 공장 초기화(`grokbot-factory-reset`)는 PIN도 지운다는 점을 기억하자.
The lock only guards a running session. The kiosk account logs in automatically, so anyone holding the device can restart it with the power button and **get the session without the PIN**. The disk may not be encrypted either. Keep the device physically safe. A factory reset (`grokbot-factory-reset`) also clears the PIN.

## 시간 바꾸기 / Change the timeouts

`~/.config/grokbot/idle.conf` (초 단위, 0 = 끔 / seconds, 0 = off), then log out or reboot:

```ini
[idle]
screen_off = 300
lock = 600
```

Grok Bot은 `lock.status` OS API로 잠금 상태를 읽을 수 있다(읽기 전용). / Grok Bot can read the lock state through the `lock.status` OS API (read-only).
