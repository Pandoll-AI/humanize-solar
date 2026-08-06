# humanize-solar

한국어 원고를 Upstage Solar로 다듬는 Claude Skill입니다. 어색한 표현과 늘어지는 문장, 굳어 있는 명사 표현을 어휘와 어순으로 고칩니다.

**문장을 쪼개지 않습니다.** 흔한 윤문 도구는 긴 문장을 만나면 일단 끊고 봅니다. 그러다 이런 일이 생깁니다.

```
원문       오분류 100건 중 61건은 바코드 훼손 또는 부착 위치 불량에서 발생하였습니다.
흔한 결과   오분류는 100건이었습니다. 이 중 61건은 바코드 훼손 또는 부착 위치 불량으로 …
이 도구     오분류 100건 중 61건은 바코드 훼손이나 부착 위치 불량에서 발생했습니다.
```

"100건 중 61건"은 포함 관계를 담은 한 덩어리입니다. 끊으면 갈 곳 없는 "이 중"이 잔해로 남습니다.

**코드블록·표·제목·인용·리스트는 건드리지 않습니다.** 모델에게 보내지도 않으니 바이트 단위로 그대로 남습니다. 고유명사·수치·영문 약어·URL도 보존합니다.

👉 **[수정 내역 보기](https://htmlpreview.github.io/?https://github.com/Pandoll-AI/humanize-solar/blob/main/examples/diff.html)** — 지운 자리와 넣은 자리를 글자 단위로 겹쳐 표시했습니다.

## 설치

```bash
git clone https://github.com/Pandoll-AI/humanize-solar.git
ln -s "$(pwd)/humanize-solar" ~/.claude/skills/humanize-solar
```

Python 3.9 이상이면 됩니다. 설치할 패키지는 없습니다.

## API 키

[Upstage Console](https://console.upstage.ai/)에서 발급합니다.

```bash
export UPSTAGE_API_KEY="up_..."
```

`~/.zshrc`나 `~/.bashrc`에 넣어 두면 편합니다.

## 사용법

```bash
python3 scripts/humanize.py 원고.md              # 결과를 화면으로
python3 scripts/humanize.py 원고.md -o 결과.md
cat 원고.md | python3 scripts/humanize.py

python3 scripts/humanize.py 원고.md --effort high
python3 scripts/humanize.py 원고.md --dry-run    # 무엇을 보낼지만 확인
```

결과는 stdout으로, 진행과 경고는 stderr로 나갑니다. 손대기 전에 `--dry-run`으로 어느 문단이 대상인지 확인해 보시는 편이 안전합니다.

### 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `-o, --output` | stdout | 결과 파일 |
| `--model` | `solar-pro4` | 모델 이름 |
| `--effort` | `medium` | `none` `minimal` `low` `medium` `high` `xhigh` `max` |
| `--temperature` | 0.5 | 표집 온도 |
| `--max-tokens` | 8192 | 응답 상한 |
| `--timeout` | 300 | 초 |
| `--dry-run` | — | 페이로드만 출력하고 종료 |

### 환경변수

| 이름 | 기본값 |
|---|---|
| `UPSTAGE_API_KEY` | (필수) |
| `UPSTAGE_BASE_URL` | `https://api.upstage.ai/v1` |
| `HUMANIZE_MODEL` | `solar-pro4` |

### reasoning effort

기본값 `medium`으로 충분합니다. 올린다고 더 많이 고치지는 않습니다 — `medium`과 `xhigh`의 편집량 차이는 0.08%포인트에 그쳤습니다.

대신 표기 정확도가 올라갑니다. 곡선따옴표처럼 미세한 문장부호가 자꾸 어긋난다면 그때 올리시면 됩니다. 추론 토큰을 함께 소모하므로 높일수록 응답이 상한에 걸릴 여지도 커집니다.

## 손대지 않는 것

- 코드블록 (` ``` ` 안쪽 전체)
- 제목 `#` · 표 `|` · 인용 `>` · 리스트 `-` `*` `+` `1.`
- 빈 줄, 구분선
- 수정 이력 마크업이 든 줄 (`<ins>`, `<del>`, `<mark>`)

일반 문단만 다듬습니다.

## 긴 문서

문단을 6,000자 또는 12개 단위로 나눠 보냅니다. 한 덩어리가 형식을 어기면 그 덩어리만 세 번까지 다시 시도하고, 그래도 안 되면 원문을 그대로 두고 경고합니다. 나머지는 계속 처리되니 전체가 실패로 끝나지 않습니다.

잘림 경고가 나오면 `--max-tokens`를 올리거나 `--effort`를 낮추십시오.

## 알아두실 점

원고에 따라 손대는 폭이 크게 다릅니다. 학술·보고문 계열은 명사화 표현이 많아 고칠 곳이 많고, 이미 잘 쓰인 구어체는 거의 그대로 지나갑니다. 손대지 않는 것도 정상적인 결과입니다.

`--temperature 0.5`가 기본이라 같은 원고를 두 번 돌리면 결과가 조금씩 다릅니다.

결과는 사람이 읽고 판단하셔야 합니다. 이 도구는 후보를 내놓을 뿐입니다.

## 형제 저장소

[humanize-qwen](https://github.com/Pandoll-AI/humanize-qwen) — 같은 일을 Alibaba Qwen으로 합니다.

## 라이선스

MIT
