"""FastAPI admin 서버 + APScheduler. tmux에서 `python server.py`로 상시 구동."""
import re
import secrets
import threading
import time
from urllib.parse import quote

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import db
from collectors import naver_price
from config import BASE_DIR, PORT, TELEGRAM_CHAT_ID, TZ
from jobs import intraday, postmarket, premarket
from notifier import telegram

db.init_db()  # SessionMiddleware가 뜨기 전에 session_secret이 먼저 필요함

app = FastAPI(title="FinanceBot Admin")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
scheduler = BackgroundScheduler(timezone=TZ)

OPEN_PATHS = {"/login", "/login/request", "/login/verify"}
_login_state = {"code": None, "expires": 0.0, "attempts": 0}


@app.middleware("http")
async def require_login(request: Request, call_next):
    if db.get_setting("require_login") != "1" or request.url.path in OPEN_PATHS:
        return await call_next(request)
    if request.session.get("authed"):
        return await call_next(request)
    if request.method == "GET":
        return RedirectResponse(f"/login?next={quote(request.url.path, safe='')}")
    return RedirectResponse("/login", status_code=303)


# SessionMiddleware는 require_login보다 나중에 등록해야 함
# (Starlette는 나중에 등록된 미들웨어를 바깥쪽에 배치 — session이 먼저 준비된 뒤 require_login이 읽어야 함)
app.add_middleware(SessionMiddleware, secret_key=db.get_session_secret(),
                    session_cookie="fb_session", max_age=60 * 60 * 24 * 30)


def _setup_jobs():
    pre_h, pre_m = db.get_setting("premarket_time").split(":")
    post_h, post_m = db.get_setting("postmarket_time").split(":")
    scheduler.add_job(premarket.run, CronTrigger(day_of_week="mon-fri", hour=int(pre_h), minute=int(pre_m)),
                      id="premarket", replace_existing=True, misfire_grace_time=600)
    scheduler.add_job(intraday.run, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5"),
                      id="intraday", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(postmarket.run, CronTrigger(day_of_week="mon-fri", hour=int(post_h), minute=int(post_m)),
                      id="postmarket", replace_existing=True, misfire_grace_time=600)


@app.on_event("startup")
def startup():
    db.init_db()
    _setup_jobs()
    scheduler.start()


# ---------- auth ----------
def _safe_next(path: str) -> str:
    """오픈 리다이렉트 방지 — 같은 오리진의 절대경로만 허용."""
    if path and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/"


def _login_target_chat_id() -> str:
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID
    for p in db.active_profiles():
        if p["telegram_chat_id"]:
            return p["telegram_chat_id"]
    return ""


@app.get("/login")
def login_page(request: Request, next: str = "/"):
    if db.get_setting("require_login") != "1":
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "login.html", {
        "next": _safe_next(next), "requested": bool(_login_state["code"]) and time.time() < _login_state["expires"],
        "error": request.query_params.get("error"), "hide_nav": True,
    })


@app.post("/login/request")
def login_request():
    code = f"{secrets.randbelow(1_000_000):06d}"
    _login_state.update(code=code, expires=time.time() + 300, attempts=0)
    telegram.send(f"🔐 FinanceBot 로그인 코드: {code}\n5분간 유효합니다.", chat_id=_login_target_chat_id())
    return RedirectResponse("/login?requested=1", status_code=303)


@app.post("/login/verify")
def login_verify(request: Request, code: str = Form(...), next: str = Form("/")):
    valid = (
        _login_state["code"] is not None
        and time.time() < _login_state["expires"]
        and _login_state["attempts"] < 5
    )
    if valid and secrets.compare_digest(code.strip(), _login_state["code"]):
        _login_state.update(code=None, expires=0.0, attempts=0)
        request.session["authed"] = True
        return RedirectResponse(_safe_next(next), status_code=303)
    _login_state["attempts"] += 1
    return RedirectResponse("/login?error=1", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------- pages ----------
@app.get("/")
def dashboard(request: Request, profile: int = 0):
    profiles = db.all_profiles()
    rows = []
    for h in db.active_holdings(profile_id=profile or None):
        snap = naver_price.get_price(h["code"]) or db.last_snapshot(h["code"], h["profile_id"]) or {}
        price = snap.get("price")
        pnl = (price - h["avg_price"]) / h["avg_price"] * 100 if price and h["avg_price"] else None
        rows.append({**h, "price": price, "change_pct": snap.get("change_pct"), "pnl_pct": pnl,
                     "value": price * h["qty"] if price else None})
    return templates.TemplateResponse(request, "dashboard.html", {
        "rows": rows, "alerts": db.recent_alerts(10, profile_id=profile or None),
        "profiles": profiles, "current_profile": profile,
        "scheduler_jobs": [(j.id, str(j.next_run_time)) for j in scheduler.get_jobs()],
    })


@app.get("/holdings")
def holdings_page(request: Request, profile: int = 0):
    profiles = db.all_profiles()
    default_profile = profile or (profiles[0]["id"] if profiles else 1)
    return templates.TemplateResponse(request, "holdings.html", {
        "holdings": db.all_holdings(profile_id=profile or None),
        "profiles": profiles, "current_profile": profile, "default_profile": default_profile,
    })


@app.get("/api/search")
def api_search(q: str = ""):
    return JSONResponse(naver_price.search_stock(q))


@app.post("/holdings/save")
def holdings_save(code: str = Form(...), name: str = Form(""), qty: int = Form(0),
                  avg_price: float = Form(0), sector: str = Form(""), memo: str = Form(""),
                  active: int = Form(1), profile_id: int = Form(1), holding_id: int = Form(0)):
    code = code.strip().zfill(6)
    if not re.fullmatch(r"\d{6}", code):
        return JSONResponse({"error": "종목코드는 숫자 6자리여야 합니다."}, status_code=400)
    if not name:
        snap = naver_price.get_price(code)
        name = snap["name"] if snap else code
    db.upsert_holding(code, name, qty, avg_price, profile_id, sector, memo, active,
                       holding_id=holding_id or None)
    return RedirectResponse(f"/holdings?profile={profile_id}", status_code=303)


@app.post("/holdings/delete")
def holdings_delete(holding_id: int = Form(...), profile_id: int = Form(1)):
    db.delete_holding(holding_id)
    return RedirectResponse(f"/holdings?profile={profile_id}", status_code=303)


@app.get("/profiles")
def profiles_page(request: Request):
    return templates.TemplateResponse(request, "profiles.html", {"profiles": db.all_profiles()})


@app.post("/profiles/save")
def profiles_save(name: str = Form(...), telegram_chat_id: str = Form(""),
                  active: int = Form(1), profile_id: int = Form(0)):
    db.upsert_profile(name.strip(), telegram_chat_id.strip(), active, profile_id=profile_id or None)
    return RedirectResponse("/profiles", status_code=303)


@app.post("/profiles/delete")
def profiles_delete(profile_id: int = Form(...)):
    db.delete_profile(profile_id)
    return RedirectResponse("/profiles", status_code=303)


@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"settings": db.all_settings()})


@app.post("/settings/save")
async def settings_save(request: Request):
    form = await request.form()
    if str(form.get("require_login", "")).strip() == "1" and not _login_target_chat_id():
        return RedirectResponse("/settings?error=no_telegram", status_code=303)
    for key in db.all_settings():
        if key in form:
            db.set_setting(key, str(form[key]).strip())
    _setup_jobs()  # 시간 변경 반영
    return RedirectResponse("/settings", status_code=303)


@app.get("/logs")
def logs_page(request: Request, profile: int = 0):
    return templates.TemplateResponse(request, "logs.html", {
        "alerts": db.recent_alerts(100, profile_id=profile or None),
        "analyses": db.recent_analyses(30, profile_id=profile or None),
        "profiles": db.all_profiles(), "current_profile": profile,
    })


# ---------- manual actions ----------
@app.post("/run/{job}")
def run_job(job: str):
    target = {"premarket": premarket.run, "intraday": intraday.run, "postmarket": postmarket.run}.get(job)
    if target:
        threading.Thread(target=target, kwargs={"force": True}, daemon=True).start()
    return RedirectResponse("/", status_code=303)


@app.post("/telegram/test")
def telegram_test():
    ok = telegram.send("✅ FinanceBot 테스트 메시지입니다.")
    return RedirectResponse(f"/settings?test={'ok' if ok else 'fail'}", status_code=303)


@app.post("/profiles/telegram_test")
def profiles_telegram_test(profile_id: int = Form(...)):
    p = db.get_profile(profile_id)
    ok = telegram.send(f"✅ [{p['name']}] FinanceBot 테스트 메시지입니다.", chat_id=p["telegram_chat_id"])
    return RedirectResponse(f"/profiles?test={'ok' if ok else 'fail'}", status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
