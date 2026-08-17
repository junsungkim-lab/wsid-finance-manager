"""로컬 Claude Code CLI(`claude -p`) 래퍼. API 키 불필요 — 맥미니 로그인 세션 사용."""
import os
import shutil
import subprocess

from config import CLAUDE_BIN


def _resolve_bin() -> str:
    path = shutil.which(CLAUDE_BIN)
    if path:
        return path
    # launchd/cron 환경은 PATH가 좁으므로 흔한 설치 경로 탐색
    for candidate in (
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ):
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("claude CLI를 찾을 수 없습니다. .env의 CLAUDE_BIN을 확인하세요.")


def ask_claude(prompt: str, web: bool = False, timeout: int = 900) -> str:
    """프롬프트를 stdin으로 전달해 headless 실행. web=True면 웹검색 허용."""
    cmd = [_resolve_bin(), "-p", "--output-format", "text"]
    if web:
        cmd += ["--allowedTools", "WebSearch,WebFetch"]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PATH": os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.local/bin")},
        )
    except subprocess.TimeoutExpired:
        return "(claude 응답 시간 초과)"
    if result.returncode != 0:
        return f"(claude 실행 실패: {result.stderr.strip()[:300]})"
    return result.stdout.strip()
