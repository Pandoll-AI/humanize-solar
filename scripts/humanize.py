#!/usr/bin/env python3
"""한국어 마크다운/텍스트 윤문 CLI — Upstage Solar API 직접 호출.

표준 라이브러리만 사용한다. 일반 문단만 API로 보내고, 코드펜스·제목·표·
인용·리스트·빈 줄·구분선은 바이트 단위로 그대로 통과시킨다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.upstage.ai/v1"
DEFAULT_MODEL = "solar-pro4"
DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 8192
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT = 300
CHUNK_MAX_CHARS = 6000
CHUNK_MAX_PARAS = 12
PARSE_RETRIES = 3
# 429/5xx 재시도 대기(초). Retry-After 헤더가 있으면 그쪽이 우선.
BACKOFF_SECS = (2, 4, 8)
MAX_HTTP_ATTEMPTS = 4
EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

BLOCK_RE = re.compile(r"\[\[(\d+)\]\]\s*(.*?)(?=\n\s*\[\[\d+\]\]|\Z)", re.DOTALL)
# 리스트: - / * / + / 1. 형태. 들여쓰기 허용.
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
# 구분선: --- *** ___ (3개 이상, 공백만 허용)
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# 수정 이력 마크업. 이 태그가 든 줄을 윤문하면 <ins>/<del> 짝이 어긋나
# 무엇을 고쳤는지 보여주려던 표시가 망가진다.
DIFF_TAG_RE = re.compile(r"</?(?:ins|del|mark)>")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

# 이 프롬프트에 금지·억제 조항을 추가하지 마라. 실측에서 '문장부호를 바꾸지 마라'
# 한 줄을 더하자 변경률이 4.34%에서 0.80%로 붕괴했다. 금지어는 그 행동을 오히려 촉발한다.
SYSTEM_PROMPT = (
    "당신은 한국어 원고 에디터다. 출력은 요청된 블록만. 코드펜스로 감싸지 마라."
)
USER_INSTRUCTION = (
    "다음 글을 독자가 한 번에 이해하도록 다듬어라.\n"
    "어색한 표현, 늘어지는 문장, 겹치는 말, 굳어 있는 명사 표현을 찾아 고쳐라.\n"
    "어순과 어휘를 손봐 읽는 흐름을 매끄럽게 만들어라.\n"
    "\n"
    "고유명사·수치·영문 약어·URL은 절대 변경 금지.\n"
    "\n"
    "출력 형식: 입력과 동일하게 [[번호]] 로 시작하는 블록을 같은 개수·같은 순서로 출력하라. "
    "번호를 빠뜨리거나 합치지 마라. 설명·머리말·꼬리말 금지."
)


# ---------------------------------------------------------------------------
# 문서 분해 · 보호 구역
# ---------------------------------------------------------------------------

def is_protected_line(line: str, in_fence: bool) -> bool:
    """보호 구역 여부. 코드펜스 내부는 무조건 보호 — 구조 문법이 깨지면 복원이 불가능하다."""
    if in_fence:
        return True
    if not line.strip():
        return True
    if DIFF_TAG_RE.search(line):
        # 수정 이력 마크업이 있는 줄. 윤문하면 <ins>/<del> 짝이 어긋나
        # 무엇을 고쳤는지 보여주려던 표시 자체가 망가진다.
        return True
    if FENCE_RE.match(line):
        return True
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return True
    if stripped.startswith("|"):
        return True
    if stripped.startswith(">"):
        return True
    if LIST_RE.match(line):
        return True
    if HR_RE.match(line):
        return True
    return False


def extract_targets(lines: list[str]) -> list[tuple[int, int, str]]:
    """윤문 대상 문단 목록 (start, end, text). end는 exclusive.

    연속된 비보호 라인을 한 문단으로 묶는다. 빈 줄·제목·표·코드펜스·인용·
    리스트·구분선을 만나면 문단이 끊긴다. 코드펜스는 토글 상태로 추적한다.
    """
    targets: list[tuple[int, int, str]] = []
    in_fence = False
    fence_marker: Optional[str] = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                # 같은 마커로 닫힌 경우만 종료. ``` 안에서 ~~~ 가 나와도 닫히지 않게.
                in_fence = False
                fence_marker = None
            i += 1
            continue

        if is_protected_line(line, in_fence):
            i += 1
            continue

        # 연속 비보호 줄 → 한 문단. 보호 라인/펜스에서 끊는다.
        start = i
        parts: list[str] = []
        while i < n and not is_protected_line(lines[i], in_fence):
            # is_protected_line이 펜스 줄도 True이므로 여기서 펜스를 삼키지 않는다.
            parts.append(lines[i])
            i += 1
        targets.append((start, i, "\n".join(parts)))

    return targets


def reassemble(lines: list[str], updates: list[tuple[int, int, str]]) -> str:
    """문단 범위(start..end)를 모델 응답으로 통째로 치환해 문서를 복원한다.

    응답 줄 수가 원문과 달라도 된다. 보호 라인은 updates에 없으므로 그대로 남는다.
    """
    if not updates:
        return "\n".join(lines)

    parts: list[str] = []
    cursor = 0
    # start 오름차순 — 앞에서부터 붙이면 인덱스 밀림을 피할 수 있다.
    for start, end, text in sorted(updates, key=lambda u: u[0]):
        parts.extend(lines[cursor:start])
        # 응답 내부 줄바꿈은 문단 본문. split 후 최종 join으로 경계를 맞춘다.
        parts.extend(text.split("\n"))
        cursor = end
    parts.extend(lines[cursor:])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 블록 프로토콜 · 청킹
# ---------------------------------------------------------------------------

def build_payload(blocks: list[str]) -> str:
    """[[n]] 블록 페이로드. round6 검증 방식을 그대로 쓴다."""
    return "\n\n".join(f"[[{i + 1}]] {b}" for i, b in enumerate(blocks))


def parse_blocks(text: str, n: int) -> Optional[list[str]]:
    """all-or-nothing 파싱.

    부분 일치 복구를 하지 않는다. 한 블록이라도 빠지거나 합쳐지면 번호 집합이
    1..n 과 어긋나고, 그때 제자리 삽입하면 문단이 밀리거나 사라진다.
    """
    found = {int(m.group(1)): m.group(2).strip() for m in BLOCK_RE.finditer(text)}
    if len(found) != n or set(found) != set(range(1, n + 1)):
        return None
    return [found[i] for i in range(1, n + 1)]


def chunk_targets(
    targets: list[tuple[int, int, str]],
    max_chars: int = CHUNK_MAX_CHARS,
    max_paras: int = CHUNK_MAX_PARAS,
) -> list[list[tuple[int, int, str]]]:
    """누적 글자 수 또는 문단 블록 수로 청크를 나눈다. 한 문단이 max_chars를 넘어도 단독 청크로 보낸다."""
    chunks: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    chars = 0

    for item in targets:
        t_len = len(item[2])
        if current and (chars + t_len > max_chars or len(current) >= max_paras):
            chunks.append(current)
            current = []
            chars = 0
        current.append(item)
        chars += t_len

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def build_messages(payload: str) -> list[dict[str, str]]:
    """system + user 메시지. user는 지시부 + 출력형식 + 구분선 + payload."""
    user = f"{USER_INSTRUCTION}\n\n---\n\n{payload}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_request_body(
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    effort: str,
) -> dict[str, Any]:
    """chat/completions 요청 본문."""
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": effort,
    }


def call_api(
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    timeout: float,
) -> tuple[str, str]:
    """POST /chat/completions. (content, finish_reason) 반환.

    429/5xx 만 지수 백오프 재시도. 그 외 HTTP 오류는 즉시 실패.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_err: Optional[BaseException] = None
    for attempt in range(MAX_HTTP_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # Upstage 응답에 이스케이프되지 않은 제어문자가 섞여 기본 strict 모드가
            # 'Invalid control character'로 실패한다. strict=False 가 필수.
            parsed = json.loads(raw, strict=False)
            choice = parsed["choices"][0]
            content = choice["message"]["content"]
            finish = choice.get("finish_reason") or ""
            return content, finish
        except urllib.error.HTTPError as e:
            last_err = e
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < MAX_HTTP_ATTEMPTS - 1:
                    wait = BACKOFF_SECS[min(attempt, len(BACKOFF_SECS) - 1)]
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra is not None:
                        try:
                            wait = max(float(ra), 0.0)
                        except ValueError:
                            pass
                    print(
                        f"경고: HTTP {e.code}, {wait:.0f}초 후 재시도 "
                        f"({attempt + 1}/{MAX_HTTP_ATTEMPTS - 1})",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
            snippet = err_body[:500] if err_body else "(본문 없음)"
            print(f"오류: HTTP {e.code}\n{snippet}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            last_err = e
            print(f"오류: 네트워크 실패 — {e.reason}", file=sys.stderr)
            sys.exit(1)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            print(f"오류: 응답 파싱 실패 — {e}", file=sys.stderr)
            sys.exit(1)

    print(f"오류: 재시도 한도 초과 — {last_err}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 윤문 파이프라인
# ---------------------------------------------------------------------------

def humanize_chunk(
    chunk: list[tuple[int, int, str]],
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    effort: str,
    timeout: float,
    chunk_idx: int,
    chunk_total: int,
) -> list[tuple[int, int, str]]:
    """한 청크를 윤문. 파싱 3회 실패 또는 finish_reason=length 면 원문 유지."""
    texts = [t for _, _, t in chunk]
    n = len(texts)
    # 청크마다 [[1]]부터 재번호 — 모델이 전역 번호를 외우게 하지 않는다.
    payload = build_payload(texts)
    messages = build_messages(payload)
    body = build_request_body(messages, model, temperature, max_tokens, effort)

    print(
        f"청크 {chunk_idx}/{chunk_total}: 문단 {n}개, {sum(len(t) for t in texts)}자",
        file=sys.stderr,
    )

    for attempt in range(1, PARSE_RETRIES + 1):
        content, finish = call_api(base_url, api_key, body, timeout)
        if finish == "length":
            # 잘린 응답을 부분 적용하면 블록이 깨진다. 이 청크는 통째로 원문 유지.
            print(
                f"경고: 청크 {chunk_idx} finish_reason=length — 원문 유지",
                file=sys.stderr,
            )
            return list(chunk)

        parsed = parse_blocks(content, n)
        if parsed is not None:
            return [(chunk[i][0], chunk[i][1], parsed[i]) for i in range(n)]

        print(
            f"경고: 청크 {chunk_idx} 블록 파싱 실패 "
            f"({attempt}/{PARSE_RETRIES})",
            file=sys.stderr,
        )

    print(
        f"경고: 청크 {chunk_idx} 파싱 {PARSE_RETRIES}회 실패 — 원문 유지",
        file=sys.stderr,
    )
    return list(chunk)


def humanize_text(
    text: str,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    effort: str,
    timeout: float,
    dry_run: bool = False,
) -> str:
    """전체 문서 윤문. dry_run 이면 첫 청크 페이로드만 stderr에 찍고 원문 반환 후 종료 유도."""
    # splitlines()는 끝 개행을 떨어뜨리므로, 원문이 개행으로 끝나면 복원 시 맞춰 준다.
    keep_trailing_nl = text.endswith("\n")
    lines = text.splitlines()
    targets = extract_targets(lines)

    if not targets:
        print("대상 문단 없음 — 원문 그대로 출력", file=sys.stderr)
        return text

    chunks = chunk_targets(targets)
    print(
        f"대상 문단 {len(targets)}개 → 청크 {len(chunks)}개",
        file=sys.stderr,
    )

    if dry_run:
        first = [t for _, _, t in chunks[0]]
        payload = build_payload(first)
        messages = build_messages(payload)
        body = build_request_body(messages, model, temperature, max_tokens, effort)
        print(json.dumps(body, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(0)

    updates: list[tuple[int, int, str]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        part = humanize_chunk(
            chunk,
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            effort=effort,
            timeout=timeout,
            chunk_idx=i,
            chunk_total=total,
        )
        updates.extend(part)

    result = reassemble(lines, updates)
    if keep_trailing_nl and not result.endswith("\n"):
        result += "\n"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """CLI 인자 파싱."""
    p = argparse.ArgumentParser(
        prog="humanize.py",
        description="한국어 마크다운/텍스트 윤문 (Upstage Solar)",
    )
    p.add_argument(
        "input",
        nargs="?",
        help="입력 파일. 생략 시 stdin",
    )
    p.add_argument("-o", "--output", dest="output", help="출력 파일. 생략 시 stdout")
    p.add_argument(
        "--model",
        default=os.environ.get("HUMANIZE_MODEL", DEFAULT_MODEL),
        help=f"모델명 (기본: {DEFAULT_MODEL}, 환경변수 HUMANIZE_MODEL)",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"temperature (기본: {DEFAULT_TEMPERATURE})",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        dest="max_tokens",
        help=f"max_tokens (기본: {DEFAULT_MAX_TOKENS})",
    )
    p.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        choices=EFFORT_VALUES,
        help=f"reasoning_effort (기본: {DEFAULT_EFFORT})",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"요청 타임아웃 초 (기본: {DEFAULT_TIMEOUT})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="요청 페이로드를 stderr에 출력하고 네트워크 호출 없이 종료",
    )
    return p.parse_args(argv)


def read_input(path: Optional[str]) -> str:
    """파일 또는 stdin에서 UTF-8 텍스트를 읽는다."""
    if path is None or path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print(f"오류: 입력 파일을 열 수 없음 — {e}", file=sys.stderr)
        sys.exit(1)


def write_output(path: Optional[str], text: str) -> None:
    """파일 또는 stdout으로 결과를 쓴다."""
    if path is None:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            if text and not text.endswith("\n"):
                f.write("\n")
    except OSError as e:
        print(f"오류: 출력 파일을 쓸 수 없음 — {e}", file=sys.stderr)
        sys.exit(1)


def main(argv: Optional[list[str]] = None) -> None:
    """진입점."""
    args = parse_args(argv)

    api_key = os.environ.get("UPSTAGE_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print(
            "오류: UPSTAGE_API_KEY 환경변수가 없습니다.\n"
            "  export UPSTAGE_API_KEY=...  후 다시 실행하세요.",
            file=sys.stderr,
        )
        sys.exit(2)

    base_url = os.environ.get("UPSTAGE_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL

    try:
        text = read_input(args.input)
        result = humanize_text(
            text,
            base_url=base_url,
            api_key=api_key or "dry-run",
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            effort=args.effort,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
        write_output(args.output, result)
    except BrokenPipeError:
        # 파이프 소비자(head 등)가 먼저 닫힌 경우 — 정상 종료로 취급
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        print("중단됨", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
