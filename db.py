import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import DB_PATH, DEFAULT_SETTINGS, TELEGRAM_CHAT_ID, TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    telegram_chat_id TEXT DEFAULT '',
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    sector TEXT DEFAULT '',
    memo TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    profile_id INTEGER NOT NULL DEFAULT 1,
    UNIQUE(code, profile_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    profile_id INTEGER NOT NULL DEFAULT 1,
    ts TEXT NOT NULL,
    price REAL,
    change_pct REAL,
    volume INTEGER,
    pnl_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(code, profile_id, ts);
CREATE TABLE IF NOT EXISTS flows (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    foreign_net INTEGER,
    inst_net INTEGER,
    indiv_net INTEGER,
    PRIMARY KEY (code, date)
);
CREATE TABLE IF NOT EXISTS disclosures (
    rcept_no TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    corp_name TEXT,
    title TEXT,
    rcept_dt TEXT,
    url TEXT,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    code TEXT DEFAULT '',
    title TEXT,
    message TEXT,
    sent INTEGER DEFAULT 0,
    profile_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    code TEXT DEFAULT '',
    content TEXT,
    profile_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS corp_codes (
    stock_code TEXT PRIMARY KEY,
    corp_code TEXT,
    corp_name TEXT
);
"""


# sqlite3는 테이블명을 파라미터 바인딩(?)할 수 없음 — f-string 삽입 전 반드시 이 allowlist로 검증한다.
_KNOWN_TABLES = {"holdings", "snapshots", "flows", "disclosures", "alerts", "analyses", "settings",
                  "corp_codes", "profiles"}


def _column_names(c, table: str) -> set[str]:
    assert table in _KNOWN_TABLES, f"알 수 없는 테이블: {table}"
    return {row["name"] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(c):
    """기존 DB(프로필 도입 이전)를 새 스키마로 이관."""
    tables = {row["name"] for row in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "profiles" not in tables:
        c.executescript("""
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_chat_id TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            );
        """)
    if c.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"] == 0:
        c.execute(
            "INSERT INTO profiles(id, name, telegram_chat_id, active) VALUES(1, '기본', ?, 1)",
            (TELEGRAM_CHAT_ID,),
        )

    if "holdings" in tables and "id" not in _column_names(c, "holdings"):
        # 구 스키마: code가 PK. id + profile_id를 가진 새 테이블로 이관.
        c.executescript("""
            CREATE TABLE holdings_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                qty INTEGER NOT NULL DEFAULT 0,
                avg_price REAL NOT NULL DEFAULT 0,
                sector TEXT DEFAULT '',
                memo TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                profile_id INTEGER NOT NULL DEFAULT 1,
                UNIQUE(code, profile_id)
            );
            INSERT INTO holdings_new(code, name, qty, avg_price, sector, memo, active, profile_id)
                SELECT code, name, qty, avg_price, sector, memo, active, 1 FROM holdings;
            DROP TABLE holdings;
            ALTER TABLE holdings_new RENAME TO holdings;
        """)

    for table in ("snapshots", "alerts", "analyses"):
        assert table in _KNOWN_TABLES, f"알 수 없는 테이블: {table}"
        if table in tables and "profile_id" not in _column_names(c, table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN profile_id INTEGER NOT NULL DEFAULT 1")


def now_kst() -> datetime:
    return datetime.now(ZoneInfo(TZ))


def now_str() -> str:
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
        row = c.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()
        if not row:
            c.execute(
                "INSERT INTO settings(key, value) VALUES('session_secret', ?)",
                (secrets.token_hex(32),),
            )


def get_session_secret() -> str:
    return get_setting("session_secret")


# ---------- settings ----------
def get_setting(key: str) -> str:
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: str):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))


def all_settings() -> dict:
    with conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------- profiles ----------
def all_profiles() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM profiles ORDER BY active DESC, id").fetchall()
    return [dict(r) for r in rows]


def active_profiles() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM profiles WHERE active=1 ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_profile(profile_id: int) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return dict(row) if row else None


def upsert_profile(name, telegram_chat_id="", active=1, profile_id: int | None = None):
    with conn() as c:
        if profile_id:
            c.execute(
                "UPDATE profiles SET name=?, telegram_chat_id=?, active=? WHERE id=?",
                (name, telegram_chat_id, active, profile_id),
            )
        else:
            c.execute(
                "INSERT INTO profiles(name, telegram_chat_id, active) VALUES(?,?,?)",
                (name, telegram_chat_id, active),
            )


def delete_profile(profile_id: int):
    with conn() as c:
        c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        c.execute("DELETE FROM holdings WHERE profile_id=?", (profile_id,))


# ---------- holdings ----------
def active_holdings(profile_id: int | None = None) -> list[dict]:
    with conn() as c:
        if profile_id:
            rows = c.execute(
                "SELECT * FROM holdings WHERE active=1 AND profile_id=? ORDER BY code", (profile_id,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM holdings WHERE active=1 ORDER BY code").fetchall()
    return [dict(r) for r in rows]


def all_holdings(profile_id: int | None = None) -> list[dict]:
    with conn() as c:
        if profile_id:
            rows = c.execute(
                "SELECT * FROM holdings WHERE profile_id=? ORDER BY active DESC, code", (profile_id,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM holdings ORDER BY active DESC, code").fetchall()
    return [dict(r) for r in rows]


def get_holding(holding_id: int) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM holdings WHERE id=?", (holding_id,)).fetchone()
    return dict(row) if row else None


def upsert_holding(code, name, qty, avg_price, profile_id, sector="", memo="", active=1, holding_id=None):
    with conn() as c:
        if holding_id:
            c.execute(
                """UPDATE holdings SET code=?, name=?, qty=?, avg_price=?, sector=?, memo=?, active=?,
                     profile_id=?
                   WHERE id=?""",
                (code, name, qty, avg_price, sector, memo, active, profile_id, holding_id),
            )
        else:
            c.execute(
                """INSERT INTO holdings(code, name, qty, avg_price, sector, memo, active, profile_id)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(code, profile_id) DO UPDATE SET
                     name=excluded.name, qty=excluded.qty, avg_price=excluded.avg_price,
                     sector=excluded.sector, memo=excluded.memo, active=excluded.active""",
                (code, name, qty, avg_price, sector, memo, active, profile_id),
            )


def delete_holding(holding_id: int):
    with conn() as c:
        c.execute("DELETE FROM holdings WHERE id=?", (holding_id,))


# ---------- snapshots ----------
def save_snapshot(code, profile_id, price, change_pct, volume, pnl_pct):
    with conn() as c:
        c.execute(
            "INSERT INTO snapshots(code, profile_id, ts, price, change_pct, volume, pnl_pct) VALUES(?,?,?,?,?,?,?)",
            (code, profile_id, now_str(), price, change_pct, volume, pnl_pct),
        )


def last_snapshot(code: str, profile_id: int) -> dict | None:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM snapshots WHERE code=? AND profile_id=? ORDER BY id DESC LIMIT 1",
            (code, profile_id),
        ).fetchone()
    return dict(row) if row else None


def today_snapshots(code: str, profile_id: int) -> list[dict]:
    today = now_kst().strftime("%Y-%m-%d")
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM snapshots WHERE code=? AND profile_id=? AND ts LIKE ? ORDER BY id",
            (code, profile_id, today + "%"),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- flows ----------
def save_flow(code, date, foreign_net, inst_net, indiv_net):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO flows(code, date, foreign_net, inst_net, indiv_net) VALUES(?,?,?,?,?)",
            (code, date, foreign_net, inst_net, indiv_net),
        )


def recent_flows(code: str, n: int = 5) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM flows WHERE code=? ORDER BY date DESC LIMIT ?", (code, n)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- disclosures ----------
def save_disclosure(rcept_no, code, corp_name, title, rcept_dt, url) -> bool:
    """신규 공시면 True (이미 본 공시면 False)."""
    with conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO disclosures(rcept_no, code, corp_name, title, rcept_dt, url, ts) VALUES(?,?,?,?,?,?,?)",
            (rcept_no, code, corp_name, title, rcept_dt, url, now_str()),
        )
        return cur.rowcount > 0


def today_disclosures(code: str | None = None) -> list[dict]:
    today = now_kst().strftime("%Y%m%d")
    with conn() as c:
        if code:
            rows = c.execute(
                "SELECT * FROM disclosures WHERE code=? AND rcept_dt=? ORDER BY rcept_no DESC", (code, today)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM disclosures WHERE rcept_dt=? ORDER BY rcept_no DESC", (today,)
            ).fetchall()
    return [dict(r) for r in rows]


# ---------- alerts / analyses ----------
def save_alert(kind, code, title, message, profile_id=1, sent=1) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO alerts(ts, kind, code, title, message, sent, profile_id) VALUES(?,?,?,?,?,?,?)",
            (now_str(), kind, code, title, message, sent, profile_id),
        )
        return cur.lastrowid


def last_alert_time(code: str, profile_id: int) -> datetime | None:
    with conn() as c:
        row = c.execute(
            "SELECT ts FROM alerts WHERE code=? AND profile_id=? AND kind='intraday' ORDER BY id DESC LIMIT 1",
            (code, profile_id),
        ).fetchone()
    if not row:
        return None
    return datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(TZ))


def in_cooldown(code: str, profile_id: int) -> bool:
    last = last_alert_time(code, profile_id)
    if not last:
        return False
    cooldown = int(float(get_setting("cooldown_min")))
    return now_kst() - last < timedelta(minutes=cooldown)


def recent_alerts(n: int = 50, profile_id: int | None = None) -> list[dict]:
    with conn() as c:
        if profile_id:
            rows = c.execute(
                "SELECT * FROM alerts WHERE profile_id=? ORDER BY id DESC LIMIT ?", (profile_id, n)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]


def save_analysis(kind, code, content, profile_id=1):
    with conn() as c:
        c.execute(
            "INSERT INTO analyses(ts, kind, code, content, profile_id) VALUES(?,?,?,?,?)",
            (now_str(), kind, code, content, profile_id),
        )


def last_intraday_analysis_today(code: str, profile_id: int) -> dict | None:
    """같은 거래일 내 해당 종목의 가장 최근 장중 분석 (후속 알림 중복 억제용)."""
    today = now_kst().strftime("%Y-%m-%d")
    with conn() as c:
        row = c.execute(
            "SELECT ts, content FROM analyses WHERE kind='intraday' AND code=? AND profile_id=? AND ts LIKE ? "
            "ORDER BY id DESC LIMIT 1",
            (code, profile_id, today + "%"),
        ).fetchone()
    return dict(row) if row else None


def recent_analyses(n: int = 20, profile_id: int | None = None) -> list[dict]:
    with conn() as c:
        if profile_id:
            rows = c.execute(
                "SELECT * FROM analyses WHERE profile_id=? ORDER BY id DESC LIMIT ?", (profile_id, n)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]


# ---------- corp codes ----------
def get_corp_code(stock_code: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT corp_code FROM corp_codes WHERE stock_code=?", (stock_code,)).fetchone()
    return row["corp_code"] if row else None


def save_corp_codes(mappings: list[tuple[str, str, str]]):
    with conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO corp_codes(stock_code, corp_code, corp_name) VALUES(?,?,?)", mappings
        )


def corp_codes_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM corp_codes").fetchone()["n"]
