"""Telegram Bot API 알림. 평문 전송(파싱 오류 방지), 4096자 제한 분할."""
import httpx

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

MAX_LEN = 4000


def send(text: str, chat_id: str | None = None) -> bool:
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("[telegram] 토큰/챗ID 미설정 — 콘솔 출력:\n" + text)
        return False
    ok = True
    for chunk in _split(text):
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"[telegram] 전송 실패 (chat_id={chat_id}): HTTP {r.status_code} {r.text[:300]}")
                ok = False
        except Exception as e:
            print(f"[telegram] 전송 예외 (chat_id={chat_id}): {e!r}")
            ok = False
    return ok


def _split(text: str) -> list[str]:
    if len(text) <= MAX_LEN:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > MAX_LEN:
            chunks.append(cur)
            cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    return chunks
