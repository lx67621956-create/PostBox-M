# PostBox-M

**에이전트가 함께 쓰는 폴더. 인프라는 그게 전부입니다.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · 한국어 · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

서로 접속할 수 없는 여러 대의 AI 에이전트가 하나의 공유 큐로 일합니다. 브로커도, 서버도, 데이터베이스도, 계정도, VPN도 필요 없습니다. 에이전트가 폴더를 읽고 쓸 수 있다면 — Google Drive, 프라이빗 git 저장소, Syncthing 동기화 폴더, USB 메모리 — 서로에게 일을 넘길 수 있습니다.

## 실제로 얻는 것

**1. 계속 띄워둘 것이 없습니다.**
메일박스는 폴더 그 자체입니다. 데몬을 배포할 필요도, 포트를 열 필요도, 토큰을 교체할 필요도, 새벽 3시에 브로커가 살아있는지 확인할 필요도 없습니다. 폴더가 있으면 시스템은 돌아갑니다. 메시지 버스의 운영 비용은 0입니다.

**2. 작업당 오너 하나를 파일 시스템이 보장합니다.**
작업 선점은 `create-if-absent`. 여섯 에이전트가 같은 작업에 몰려도 성공은 정확히 하나, 나머지 다섯은 종료 코드 3으로 물러납니다. 중복 작업이 사라지는 이유는 둘이 "합의해서"가 아니라, 한쪽이 **물리적으로 그 파일을 만들 수 없었기** 때문입니다.

**3. 어떤 것도 덮어쓰지 않습니다.**
작업은 한 번 쓰이고 다시 편집되지 않습니다. 확인·진행 기록·납품·블로킹, 모든 행동이 고유한 이름의 새 파일입니다. 그래서 작업 이력은 규율이 아니라 **구조적으로** 완전합니다. git 백엔드에서는 `git log`가 "누가 언제 무엇을 선점했는지"를 제3자에게 증명합니다.

**4. 변화가 없으면 폴링은 무료입니다.**
`postbox watch`는 폴더가 그대로인 동안 바이트 단위로 동일한 출력을 내고 종료 코드 0을 돌려줍니다. cron은 출력(또는 종료 코드만)을 비교해 모델 호출을 통째로 건너뜁니다. 대기 중인 에이전트는 토큰을 쓰지 않고, 정말 새 일이 있을 때만 깨어납니다.

**5. 납품물은 해시가 붙은 파일이고, 문장이 아닙니다.**
`postbox result --artifact report.md`는 파일·폴더·크기·sha256을 영수증에 적습니다. 채팅에서 "완료했습니다"라고 말해도 납품이 아니며, 도구는 그것을 납품으로 기록하지 않습니다.

**6. 이미 있는 환경에서 돕니다.**
Gitee 프라이빗 저장소, Nutstore WebDAV, SSH로 접속하는 자기 VPS, Google Drive, 같은 LAN의 노트북 두 대. 구글 계정도, VPN도, 인바운드 포트도 필요 없습니다.

**7. 의존성 제로.**
파이썬 표준 라이브러리만 사용, Python 3.9 이상, 명령 하나. 컴파일 없음, lockfile 없음, 감사할 공급망 없음.

## 설치

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
```

소스에서 설치: `git clone … && uv tool install .`

## 60초 안에 돌려보기

```bash
# 머신 A
postbox init --transport local --path "~/Dropbox/team-inbox" --agent alice
postbox new --to bob --title "주간 리포트" --ask "핵심 다섯 개, 숫자만."

# 머신 B
postbox init --transport local --path "~/Dropbox/team-inbox" --agent bob
postbox inbox          # 작업 1개, alice가 보냄
postbox ack <id>
postbox result <id> --artifact weekly.md --text "45주차 숫자, 출처는 파일 안에"
```

루프는 이게 전부입니다. 나머지 `watch`·`lint`·`doctor`는 무인으로 계속 돌리기 위한 장치입니다.

## 백엔드 고르기

`postbox providers`가 모든 선택지와 실행 가능한 명령을 보여줍니다:

| 프리셋 | 중국 본토 사용 가능 | 무엇인가 |
|---|---|---|
| `git` | 예 | Gitee / GitHub / 자기 VPS의 프라이빗 저장소, 쓰기 1회당 커밋 1개 |
| `local` | 예 | 기존 동기화 도구가 이미 복제하는 아무 폴더 |
| `webdav` | 예 | Nutstore, Nextcloud, Alist |
| `sftp` | 예 | 이미 가진 VPS |
| `s3` | 경우에 따라 | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | 아니오 | Google Drive |
| `onedrive` / `dropbox` | 아니오 | OneDrive, Dropbox |

`local`은 rclone도 OAuth도 계정도 네트워크도 필요 없습니다. 같은 폴더를 가리키는 두 개의 체크아웃이 곧 동작하는 메일박스이며, 테스트 스위트도 그렇게 돌아갑니다.

## AI 에이전트를 위해

큐가 작동하려면 모든 에이전트가 같은 규칙을 따라야 하므로, 규칙도 도구와 함께 배포합니다:

```bash
postbox instructions > AGENTS.md
```

루프(작업 전에 선점, 결과에는 매니페스트), 단단한 규칙(남의 파일을 편집하지 않는다, 비밀을 쓰지 않는다), 그리고 종료 코드의 의미 — 어느 것이 "경쟁에서 졌다"이고 어느 것이 "메일박스에 닿지 않는다"인지 — 를 담고 있습니다. 시스템 프롬프트, `AGENTS.md`, `CLAUDE.md`, 프로젝트 스킬 어디에 붙여도 됩니다.

## 작은 단서

두 가지만: 동기화 폴더는 클라이언트가 실제로 전달한 뒤에야 파일이 보이므로 폴링 간격을 동기화 지연보다 길게 두세요. 그리고 두 편집이 충돌하면 데스크톱 클라이언트가 `foo.md` 옆에 `foo (1).md`를 만듭니다 — `lint`가 보고하고, 원본은 그대로입니다. 이 시스템은 어떤 것도 제자리에서 덮어쓰지 않기 때문입니다.

더 깊은 내용: [`docs/protocol.md`](docs/protocol.md)(규격), [`docs/design-notes.md`](docs/design-notes.md)(설계 이유).

## 만든 사람

**闷闷AI说** — 과장 없이 전하는 중국어 AI 뉴스.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT 라이선스.
