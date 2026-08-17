"""yfinance로 밤사이 미장 지수/섹터 ETF/환율 요약."""
TICKERS = {
    "^GSPC": "S&P500",
    "^IXIC": "나스닥",
    "^DJI": "다우",
    "^SOX": "필라델피아 반도체",
    "^VIX": "VIX",
    "KRW=X": "원/달러",
    "CL=F": "WTI 유가",
    "XLK": "기술 ETF",
    "XLE": "에너지 ETF",
    "XLF": "금융 ETF",
    "XLV": "헬스케어 ETF",
    "XLI": "산업재 ETF",
}


def us_summary_text() -> str:
    """전일 대비 등락률 요약 문자열. 실패한 티커는 건너뜀."""
    try:
        import yfinance as yf

        data = yf.download(list(TICKERS), period="5d", progress=False, group_by="ticker", threads=True)
    except Exception as e:
        return f"미장 데이터 수집 실패: {e}"
    lines = []
    for ticker, label in TICKERS.items():
        try:
            closes = data[ticker]["Close"].dropna()
            if len(closes) < 2:
                continue
            last, prev = closes.iloc[-1], closes.iloc[-2]
            pct = (last - prev) / prev * 100
            lines.append(f"{label}: {last:,.2f} ({pct:+.2f}%)")
        except Exception:
            continue
    return "\n".join(lines) if lines else "미장 데이터 없음"
