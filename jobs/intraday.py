"""장중 5분 모니터링 — 스냅샷 저장 + 트리거 감지 → claude 판단 보조 → Telegram."""
import db
import market_calendar as cal
from analyzer.claude_cli import ask_claude
from analyzer.prompts import intraday_followup_prompt, intraday_prompt
from collectors import dart, naver_flow, naver_price
from notifier import telegram

# 전일 총거래량 캐시 (프로세스 생명주기 동안 하루 단위 갱신)
_prev_volume_cache: dict[str, tuple[str, int]] = {}


def _prev_volume(code: str) -> int | None:
    today = db.now_kst().strftime("%Y%m%d")
    cached = _prev_volume_cache.get(code)
    if cached and cached[0] == today:
        return cached[1]
    v = naver_price.get_prev_volume(code, today)
    if v:
        _prev_volume_cache[code] = (today, v)
    return v


def detect_triggers(h: dict, snap: dict, prev_snap: dict | None, new_disclosures: list[dict]) -> list[str]:
    triggers = []
    s = db.all_settings()
    change_th = float(s["change_pct_threshold"])
    spike_th = float(s["spike_5m_threshold"])
    loss_levels = sorted((float(x) for x in s["loss_levels"].split(",") if x.strip()), reverse=True)

    if new_disclosures:
        triggers.append(f"신규 공시 {len(new_disclosures)}건")

    if snap["change_pct"] is not None and abs(snap["change_pct"]) >= change_th:
        triggers.append(f"당일 등락 {snap['change_pct']:+.1f}%")

    if prev_snap and prev_snap.get("price") and snap["price"]:
        move = (snap["price"] - prev_snap["price"]) / prev_snap["price"] * 100
        if abs(move) >= spike_th:
            triggers.append(f"5분 급변 {move:+.1f}%")

    # 손실 임계선 최초 하향 돌파 (직전 스냅샷 손익률과 비교)
    pnl = snap["pnl_pct"]
    prev_pnl = prev_snap.get("pnl_pct") if prev_snap else None
    if pnl is not None:
        for level in loss_levels:
            if pnl <= level and (prev_pnl is None or prev_pnl > level):
                triggers.append(f"손실 {level:.0f}% 선 돌파 (현재 {pnl:+.1f}%)")
                break

    prev_vol = _prev_volume(h["code"])
    if prev_vol and snap["volume"] and snap["volume"] > prev_vol:
        already = prev_snap and prev_snap.get("volume") and prev_snap["volume"] > prev_vol
        if not already:  # 하루 한 번만
            triggers.append("거래량 전일 총량 초과")

    return triggers


def _day_context(code: str, profile_id: int) -> str:
    snaps = db.today_snapshots(code, profile_id)
    if not snaps:
        return "(데이터 없음)"
    step = max(1, len(snaps) // 12)  # 최대 ~12포인트로 압축
    pts = snaps[::step][-12:]
    return " → ".join(f"{s['ts'][11:16]} {s['price']:,.0f}" for s in pts if s["price"])


def run(force: bool = False):
    if not force and not (cal.is_trading_day() and cal.in_market_hours()):
        return
    use_claude = db.get_setting("use_claude_intraday") == "1"

    price_cache: dict[str, dict] = {}   # 프로필 간 중복 API 호출 방지 (코드 단위 시세는 공용)
    disc_cache: dict[str, list] = {}

    for profile in db.active_profiles():
        pid = profile["id"]
        chat_id = profile["telegram_chat_id"]

        for h in db.active_holdings(profile_id=pid):
            code = h["code"]
            if code not in price_cache:
                price_cache[code] = naver_price.get_price(code)
            snap_data = price_cache[code]
            if not snap_data or snap_data["price"] is None:
                print(f"[intraday] {code} 시세 수집 실패")
                continue

            if code not in disc_cache:
                disc_cache[code] = dart.check_new_disclosures(code)
            new_disc = disc_cache[code]

            pnl_pct = (snap_data["price"] - h["avg_price"]) / h["avg_price"] * 100 if h["avg_price"] else None
            prev_snap = db.last_snapshot(code, pid)
            snap = {**snap_data, "pnl_pct": pnl_pct}

            triggers = detect_triggers(h, snap, prev_snap, new_disc)

            db.save_snapshot(code, pid, snap["price"], snap["change_pct"], snap["volume"], pnl_pct)

            if not triggers or db.in_cooldown(code, pid):
                continue

            head = (f"🚨 [{profile['name']}] {h['name']}({code}) 트리거 발생\n"
                    f"현재가 {snap['price']:,.0f}원 (당일 {snap['change_pct']:+.2f}% / 평단 대비 {pnl_pct:+.2f}%)\n"
                    f"트리거: {', '.join(triggers)}")
            if new_disc:
                head += "\n" + "\n".join(f"📄 {d['title']}\n{d['url']}" for d in new_disc[:3])

            if use_claude:
                flow_text = naver_flow.flow_summary_text(code)
                prev = db.last_intraday_analysis_today(code, pid)
                if prev:
                    # 후속 알림 — 배경 반복 없이 직전 대비 변화만 짧게
                    analysis = ask_claude(
                        intraday_followup_prompt(h, snap, triggers, flow_text, new_disc,
                                                 _day_context(code, pid), prev["content"], prev["ts"]),
                        web=True, timeout=400,
                    )
                    msg = analysis  # 후속은 자체 헤더(🔁)만, 중복 head 생략
                else:
                    # 첫 알림 — 풀 분석
                    analysis = ask_claude(
                        intraday_prompt(h, snap, triggers, flow_text, new_disc, _day_context(code, pid)),
                        web=True, timeout=600,
                    )
                    msg = f"{head}\n\n{analysis}"
                db.save_analysis("intraday", code, analysis, profile_id=pid)
            else:
                msg = head + "\n\n※ 투자 판단 참고용이며 최종 결정과 책임은 본인에게 있습니다."

            telegram.send(msg, chat_id=chat_id)
            db.save_alert("intraday", code, ", ".join(triggers), msg, profile_id=pid)
            print(f"[intraday] [{profile['name']}] {code} 알림 전송: {triggers}")


if __name__ == "__main__":
    run(force=True)
