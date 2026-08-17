"""네이버 금융 실시간 시세 (무료, 비공식 polling API)."""
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _num(s, cast=float):
    if s is None:
        return None
    try:
        return cast(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def get_price(code: str) -> dict | None:
    """현재가/등락률/누적거래량. 실패 시 None."""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        datas = r.json().get("datas") or []
        if not datas:
            return None
        d = datas[0]
        sign = -1 if str(d.get("compareToPreviousPrice", {}).get("code", "")) in ("4", "5") else 1
        change_pct = _num(d.get("fluctuationsRatio"))
        if change_pct is not None and change_pct > 0:
            change_pct *= sign
        return {
            "code": code,
            "name": d.get("stockName", code),
            "price": _num(d.get("closePrice")),
            "change_pct": change_pct,
            "volume": _num(d.get("accumulatedTradingVolume"), int),
            "market_status": d.get("marketStatus", ""),
        }
    except Exception:
        return None


def get_index(name: str) -> dict | None:
    """코스피/코스닥 지수 실시간. name: 'KOSPI' | 'KOSDAQ'."""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{name}"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        d = (r.json().get("datas") or [None])[0]
        if not d:
            return None
        sign = -1 if str(d.get("compareToPreviousPrice", {}).get("code", "")) in ("4", "5") else 1
        change = _num(d.get("compareToPreviousClosePrice"))
        pct = _num(d.get("fluctuationsRatio"))
        return {
            "name": d.get("stockName", name),
            "value": _num(d.get("closePrice")),
            "change": change * sign if change is not None else None,
            "change_pct": pct * sign if pct is not None else None,
        }
    except Exception:
        return None


def index_summary_text() -> str:
    """코스피·코스닥 지수 요약 문자열 (프롬프트용)."""
    lines = []
    for code in ("KOSPI", "KOSDAQ"):
        idx = get_index(code)
        if idx and idx["value"] is not None:
            lines.append(f"{idx['name']}: {idx['value']:,.2f} ({idx['change_pct']:+.2f}%, {idx['change']:+,.2f}p)")
    return "\n".join(lines) if lines else "지수 데이터 없음"


def search_stock(query: str, limit: int = 8) -> list[dict]:
    """종목명/코드로 국내 주식 검색 (네이버 자동완성). [{code, name, market}]."""
    query = query.strip()
    if not query:
        return []
    url = "https://ac.stock.naver.com/ac"
    try:
        r = httpx.get(url, params={"q": query, "target": "stock", "st": "111"},
                      headers=HEADERS, timeout=10)
        r.raise_for_status()
        out = []
        for it in r.json().get("items", []):
            # 국내(KOR) 주식만
            if it.get("nationCode") != "KOR" or it.get("category") != "stock":
                continue
            out.append({
                "code": it.get("code", ""),
                "name": it.get("name", ""),
                "market": it.get("typeName", ""),  # 코스피/코스닥
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def get_prev_volume(code: str, today_yyyymmdd: str) -> int | None:
    """전일 총거래량 (거래량 폭발 트리거용) — trend API의 일자별 누적거래량 사용."""
    url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=3&page=1"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        for it in r.json():
            if it.get("bizdate", "") != today_yyyymmdd:  # 가장 최근의 전 거래일
                return _num(it.get("accumulatedTradingVolume"), int)
    except Exception:
        pass
    return None
