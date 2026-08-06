# humanize-solar

한국어 원고를 Upstage Solar로 다듬는 Claude Skill입니다. 어색한 표현과 늘어지는 문장, 굳어 있는 명사 표현을 어휘와 어순으로 고칩니다.

**문장을 쪼개지 않습니다.** 흔한 윤문 도구는 긴 문장을 만나면 일단 끊고 봅니다. 그러다 "오분류 100건 중 61건은…"이 "오분류는 100건이었습니다. 이 중 61건은…"으로 갈라져 갈 곳 없는 "이 중"이 잔해로 남습니다. 이 도구는 끊지 않고 어휘와 어순만 손봅니다.

실제로 돌린 결과입니다. <del>취소선</del>이 지운 자리, <mark>노란 배경</mark>이 새로 넣은 자리입니다.

<table>
<tr><td><br>&nbsp;시범 기간 <del>중 </del>자동분류기<del>를</del> <del>통과한</del><mark>처리</mark> 물량은 총 12,480건으로, 같은 기간 대상 라인 전체 처리<del> 물</del>량의 약 31%<del>에 해당합</del><mark>입</mark>니다. 설비<del> 자체의</del> 분류 정확도는 99.2%로 집계되었<del>고</del><mark>으며</mark>, 오분류 100건 중 61건은 바코드 훼손<del> 또는</del><mark>이나</mark> 부착 위치 불량에서 발생<del>하였</del><mark>했</mark>습니다.&nbsp;<br><br></td></tr>
<tr><td><br>&nbsp;인천남동물류센터 자동분류기 도입 1차 시범 운영 결과를 <del>다음과 같이 </del>보고<del>드립</del><mark>합</mark>니다.<del> 본</del> 시범 운영은 2026년 7월 6일부터 7월 19일까지 14일간 진행<del>하였</del><mark>했</mark>으며, 출고 물량이 집중되는 오후 시간대를 중심으로 기존 수작업 분류<del> 공정과</del><mark>와</mark> 병행<del>하여 운영하였</del><mark>했</mark>습니다.&nbsp;<br><br></td></tr>
</table>

**코드블록·표·제목·인용·리스트는 건드리지 않습니다.** 모델에게 보내지도 않으니 바이트 단위로 그대로 남습니다. 고유명사·수치·영문 약어·URL도 보존합니다.

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
