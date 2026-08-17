"""16:00 마감 정리 — 오늘 국장 이슈 + 보유 종목별 등락/수급(확정)/공시 요약."""
import db
import market_calendar as cal
from analyzer.claude_cli import ask_claude
from analyzer.prompts import postmarket_prompt
from collectors import naver_flow, naver_price
from notifier import telegram


def _holdings_summary(profile_id: int) -> str:
    lines = []
    for h in db.active_holdings(profile_id=profile_id):
        snap = naver_price.get_price(h["code"])
        if not snap or snap["price"] is None:
            last = db.last_snapshot(h["code"], profile_id)
            if not last:
                lines.append(f"- {h['name']}({h['code']}): 시세 조회 실패")
                continue
            snap = last
        pnl = (snap["price"] - h["avg_price"]) / h["avg_price"] * 100 if h["avg_price"] else 0
        line = (f"- {h['name']}({h['code']}): 종가 {snap['price']:,.0f}원 "
                f"(당일 {snap['change_pct']:+.2f}%, 평단 대비 {pnl:+.2f}%)")
        flow = naver_flow.flow_summary_text(h["code"]).split("\n")[0]
        line += f"\n  수급(최근): {flow}"
        lines.append(line)
    return "\n".join(lines) if lines else "(보유 종목 없음)"


def run(force: bool = False):
    if not force and not cal.is_trading_day():
        print("[postmarket] 휴장일 — 스킵")
        return
    index_text = naver_price.index_summary_text()
    discs = db.today_disclosures()
    disc_text = "\n".join(f"- {d['corp_name']}: {d['title']}" for d in discs) or "(없음)"
    print("[postmarket] 데이터 수집 완료, claude 분석 시작")

    for profile in db.active_profiles():
        summary = _holdings_summary(profile["id"])
        analysis = ask_claude(postmarket_prompt(summary, disc_text, index_text), web=True)
        msg = f"🌙 [{profile['name']}] 마감 브리핑 ({db.now_kst().strftime('%m/%d (%a)')})\n\n{analysis}"
        telegram.send(msg, chat_id=profile["telegram_chat_id"])
        db.save_analysis("postmarket", "", analysis, profile_id=profile["id"])
        db.save_alert("postmarket", "", "마감 브리핑", msg, profile_id=profile["id"])
        print(f"[postmarket] [{profile['name']}] 완료")


if __name__ == "__main__":
    run(force=True)
