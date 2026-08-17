import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / "financebot.db"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DART_API_KEY = os.getenv("DART_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
PORT = int(os.getenv("PORT", "8010"))

TZ = "Asia/Seoul"

# settings 테이블 기본값 (admin에서 수정 가능)
DEFAULT_SETTINGS = {
    "change_pct_threshold": "3.0",    # 당일 등락률 트리거 (%)
    "spike_5m_threshold": "1.5",      # 5분 급변 트리거 (%)
    "loss_levels": "-5,-10,-15",      # 평단 대비 손실 임계선 (%)
    "cooldown_min": "30",             # 종목별 알림 쿨다운 (분)
    "use_claude_intraday": "1",       # 장중 트리거 시 claude 분석 사용 (0이면 룰 기반 알림만)
    "premarket_time": "08:00",
    "postmarket_time": "16:00",
    "require_login": "0",             # 관리 화면 접속 시 텔레그램 인증코드 로그인 요구 (기본 꺼짐 — /settings에서 켜기)
}
