"""KRX 거래일/장중 판정. exchange_calendars(XKRX) 사용, 실패 시 주중 판정으로 폴백."""
from datetime import time

from db import now_kst

try:
    import exchange_calendars as xcals

    _krx = xcals.get_calendar("XKRX")
except Exception:
    _krx = None

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


def is_trading_day() -> bool:
    now = now_kst()
    if _krx is not None:
        try:
            return _krx.is_session(now.strftime("%Y-%m-%d"))
        except Exception:
            pass
    return now.weekday() < 5


def in_market_hours() -> bool:
    t = now_kst().time()
    return MARKET_OPEN <= t <= MARKET_CLOSE
