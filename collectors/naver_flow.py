"""수급(투자자별 매매동향). 네이버 trend API 기본(수량 기준), pykrx는 KRX 계정 설정 시 보조.

pykrx 1.0.51+는 KRX_ID/KRX_PW 환경변수(KRX 정보데이터시스템 계정)가 필요해
계정 없이도 동작하는 네이버 trend API를 주 소스로 사용한다.
"""
import httpx

import db

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _qty(s):
    if s is None:
        return None
    try:
        return int(str(s).replace(",", "").replace("+", ""))
    except (ValueError, TypeError):
        return None


def fetch_trend(code: str, n: int = 10) -> list[dict]:
    """일별 외인/기관/개인 순매수량(주) + 외인 보유비율. 최신순. DB에도 저장."""
    url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize={n}&page=1"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            biz = it.get("bizdate", "")
            date = f"{biz[:4]}-{biz[4:6]}-{biz[6:]}" if len(biz) == 8 else biz
            row = {
                "date": date,
                "foreign_net": _qty(it.get("foreignerPureBuyQuant")),
                "inst_net": _qty(it.get("organPureBuyQuant")),
                "indiv_net": _qty(it.get("individualPureBuyQuant")),
                "foreign_ratio": it.get("foreignerHoldRatio", ""),
                "close": _qty(it.get("closePrice")),
            }
            out.append(row)
            db.save_flow(code, date, row["foreign_net"], row["inst_net"], row["indiv_net"])
        return out
    except Exception:
        return [
            {**f, "foreign_ratio": "", "close": None} for f in db.recent_flows(code)
        ]


def flow_summary_text(code: str, n: int = 5) -> str:
    """claude 프롬프트/텔레그램용 수급 요약 (순매수량 기준)."""
    trends = fetch_trend(code, n)
    if not trends:
        return "수급 데이터 없음"

    def fmt(v):
        if v is None:
            return "?"
        if abs(v) >= 10000:
            return f"{v / 10000:+,.1f}만주"
        return f"{v:+,}주"

    lines = []
    for t in trends[:n]:
        line = f"{t['date']}: 외인 {fmt(t['foreign_net'])} / 기관 {fmt(t['inst_net'])} / 개인 {fmt(t['indiv_net'])}"
        if t.get("foreign_ratio"):
            line += f" (외인보유 {t['foreign_ratio']})"
        lines.append(line)
    return "\n".join(lines)
