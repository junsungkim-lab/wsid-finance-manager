"""DART 공시 조회. corp_code 매핑(corpCode.xml)은 최초 1회 다운로드 후 DB 캐시."""
import io
import xml.etree.ElementTree as ET
import zipfile

import httpx

import db
from config import DART_API_KEY
from db import now_kst

BASE = "https://opendart.fss.or.kr/api"


def ensure_corp_codes():
    """corp_code 매핑이 비어 있으면 DART에서 전체 다운로드해 캐시."""
    if not DART_API_KEY or db.corp_codes_count() > 0:
        return
    r = httpx.get(f"{BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=60)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml_data = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_data)
    mappings = []
    for el in root.iter("list"):
        stock_code = (el.findtext("stock_code") or "").strip()
        if stock_code:
            mappings.append((stock_code, el.findtext("corp_code", "").strip(), el.findtext("corp_name", "").strip()))
    if mappings:
        db.save_corp_codes(mappings)


def check_new_disclosures(stock_code: str) -> list[dict]:
    """오늘자 공시 조회 → DB에 없던 신규 공시만 반환."""
    if not DART_API_KEY:
        return []
    ensure_corp_codes()
    corp_code = db.get_corp_code(stock_code)
    if not corp_code:
        return []
    today = now_kst().strftime("%Y%m%d")
    try:
        r = httpx.get(
            f"{BASE}/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bgn_de": today,
                "end_de": today,
                "page_count": 50,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "000":  # 013 = 조회 결과 없음
            return []
        new_items = []
        for it in data.get("list", []):
            rcept_no = it.get("rcept_no", "")
            url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            is_new = db.save_disclosure(
                rcept_no, stock_code, it.get("corp_name", ""), it.get("report_nm", ""),
                it.get("rcept_dt", today), url,
            )
            if is_new:
                new_items.append({"rcept_no": rcept_no, "title": it.get("report_nm", ""), "url": url})
        return new_items
    except Exception:
        return []
