"""08:00 프리마켓 브리핑 — 밤사이 미장 이슈 + 보유 섹터/신규 섹터 분석."""
import db
import market_calendar as cal
from analyzer.claude_cli import ask_claude
from analyzer.prompts import premarket_prompt
from collectors import naver_price
from collectors.us_market import us_summary_text
from notifier import telegram


def run(force: bool = False):
    if not force and not cal.is_trading_day():
        print("[premarket] 휴장일 — 스킵")
        return
    us = us_summary_text()
    index_text = naver_price.index_summary_text()
    print("[premarket] 미장 데이터 수집 완료, claude 분석 시작")

    for profile in db.active_profiles():
        holdings = db.active_holdings(profile_id=profile["id"])
        analysis = ask_claude(premarket_prompt(holdings, us, index_text), web=True)
        msg = f"🌅 [{profile['name']}] 프리마켓 브리핑 ({db.now_kst().strftime('%m/%d (%a)')})\n\n{analysis}"
        telegram.send(msg, chat_id=profile["telegram_chat_id"])
        db.save_analysis("premarket", "", analysis, profile_id=profile["id"])
        db.save_alert("premarket", "", "프리마켓 브리핑", msg, profile_id=profile["id"])
        print(f"[premarket] [{profile['name']}] 완료")


if __name__ == "__main__":
    run(force=True)
