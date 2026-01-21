import os, time, math, asyncio, ssl, smtplib
from email.message import EmailMessage
from typing import Dict, Any, Optional, Tuple, List, Set

import aiohttp
from dotenv import load_dotenv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()

# =========================================================
# ADMIN (GitHub-backed overrides)
# =========================================================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123").strip()
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "change-me").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()  # e.g. owner/repo
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PRICES_FILE = os.path.join(DATA_DIR, "admin_prices.json")
ROOM_STATUS_FILE = os.path.join(DATA_DIR, "admin_room_status.json")

os.makedirs(DATA_DIR, exist_ok=True)


# =========================================================
# FASTAPI
# =========================================================

# =========================================================
# GitHub file helpers (optional)
# =========================================================
def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: str, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _make_session(value: str) -> str:
    sig = hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"

def _verify_session(cookie_val: str) -> bool:
    try:
        value, sig = cookie_val.rsplit(".", 1)
        expected = hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

async def _github_get_file_sha(session: aiohttp.ClientSession, path: str) -> str:
    # returns SHA or "" if not exist
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return ""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    params = {"ref": GITHUB_BRANCH}
    async with session.get(url, headers=headers, params=params) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("sha", "")
        return ""

async def _github_commit_file(path_in_repo: str, content_bytes: bytes, message: str):
    # If GitHub is configured, commit file; otherwise only write local.
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        sha = await _github_get_file_sha(session, path_in_repo)
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path_in_repo}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode("utf-8"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        async with session.put(url, headers=headers, json=payload) as resp:
            if resp.status not in (200, 201):
                txt = await resp.text()
                raise RuntimeError(f"GitHub commit failed: {resp.status} {txt}")


def apply_admin_overrides_to_property(prop: Dict[str, Any], prices: Dict[str, Any], statuses: Dict[str, Any]):
    code = prop.get("code") or prop.get("property_code") or ""
    if not code:
        return
    p_override = prices.get(code, {}) if isinstance(prices, dict) else {}
    if "today_price" in p_override:
        prop["today_price"] = p_override["today_price"]
    if "standard_price" in p_override:
        prop["standard_price"] = p_override["standard_price"]

    # room status overrides + availability count
    rooms = prop.get("rooms") or []
    status_map = (statuses.get(code) or {}) if isinstance(statuses, dict) else {}
    available_count = 0
    for r in rooms:
        room_no = str(r.get("room") or r.get("room_no") or r.get("number") or "")
        if room_no and room_no in status_map:
            st = status_map[room_no]
            r["booking_status"] = st
        # Default logic: treat not booked as available
        st_val = (r.get("booking_status") or r.get("status") or "available").lower()
        if st_val == "available":
            available_count += 1
    prop["available_rooms"] = available_count


def load_overrides():
    prices = _read_json(PRICES_FILE, {})
    statuses = _read_json(ROOM_STATUS_FILE, {})
    return prices, statuses

app = FastAPI(title="Hotel Booking API - Production (OYO + Telegram)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# COMPANY / BUSINESS SETTINGS
# =========================================================
COMPANY_NAME = "Properties Group Hyderabad (PGH)"

# =========================================================
# ROOM PHOTOS ROOT
# Folder Structure:
# /home/ubuntu/hotel-booking/room_photos/<PROPERTY>/<ROOM>/*.jpg|png|webp
# =========================================================
ROOM_PHOTOS_ROOT = "/home/ubuntu/hotel-booking/room_photos"

def _safe_join(*parts):
    # safe path join (avoid ..)
    p = os.path.join(*[str(x) for x in parts])
    return os.path.normpath(p)

def list_room_images(prop_code: str, room_no: str) -> List[str]:
    """
    Returns list of relative image URLs for a given property room.
    This does NOT serve static files itself. You will use nginx to serve /room_photos/ alias.
    """
    prop_code = (prop_code or "").strip()
    room_no = (room_no or "").strip()
    if not prop_code or not room_no:
        return []

    room_dir = _safe_join(ROOM_PHOTOS_ROOT, prop_code, room_no)
    if not room_dir.startswith(os.path.normpath(ROOM_PHOTOS_ROOT)):
        return []

    if not os.path.isdir(room_dir):
        return []

    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = []
    try:
        for f in os.listdir(room_dir):
            if f.lower().endswith(exts):
                files.append(f)
    except Exception:
        return []

    files.sort()
    # nginx static: /room_photos/<PROP>/<ROOM>/<FILE>
    return [f"/room_photos/{prop_code}/{room_no}/{fn}" for fn in files]

# =========================================================
# PROPERTIES
# =========================================================
PROPERTIES: Dict[str, Dict[str, Any]] = {
    "HYD2857": {"UIF":"eyJlbWFpbCI6Im1vaGRzdWFpZGFobWVkQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6Ilo1ZUpSMVJiN3FOb3pNNWY0by10YkEiLCJyb2xlIjoiT3duZXIiLCJpZCI6MjAzMzEzMjUyLCJwaG9uZSI6Ijk5ODUyODMzMDYiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTczMjI2MTE0MiIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ3MjgyMDk3NDkzLCJhZGRyZXNzSnNvbiI6e319","UUID":"NDFlNWI1ZTQtODFiZC00MWQ1LWIwODAtM2FmMzcwOGYwYmQz","QID":259690},
    "HYD2728": {"UIF":"eyJlbWFpbCI6ImNoZWYubml0aW5AZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoicGZnNXFBLWNNbTVGZXpQZVktelVrZyIsInJvbGUiOiJPd25lciIsImlkIjoyMDQ3MjI0OTMsInBob25lIjoiOTEwMDA5MjU4NiIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzIwNzkzNTg3IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5MTQyOTAzODU4ODcsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"ZjNkOTczZDItYTVmNS00N2NkLWJlMWItNzUzOGRlMDdhZjM5","QID":245844},
    "HYD2927": {"UIF":"eyJlbWFpbCI6InVwcGFsYXNhaTg4QGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IlVCTjcxVDB0aFJlZXZpemxRbEVrbmciLCJyb2xlIjoiT3duZXIiLCJpZCI6MjE2Mzk4NDcwLCJwaG9uZSI6Ijg2ODYwNjY2NjYiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTczNzc4NTUxNCIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ4NzI2ODk5NDY3LCJhZGRyZXNzSnNvbiI6e319","UUID":"ODczOWYwMzMtYzQ5YS00NTRkLWFhNWUtNTJmOTdmYjQ3OWNj","QID":292909},
    "HYD3030": {"UIF":"eyJlbWFpbCI6InN2aG90ZWw5OTlAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoic2x5Y2Fta0pBbU9uZUt2SXlwOWVsUSIsInJvbGUiOiJPd25lciIsImlkIjoyMzU5NTMyNTAsInBob25lIjoiOTk4NTM0NzQ3NiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJHdWVzdCIsInNleCI6Ik1hbGUiLCJ0ZWFtIjoiTWFya2V0aW5nIiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwidXBkYXRlZF9hdCI6IjE3NTM4ODQzOTEiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk0MDI5NDU3MjI0MywiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"ZjNjZmZkMWQtOTJiMS00ZjM3LWE1YWMtZGQ3NGExNGIwN2Q5","QID":304236},
    "HYD1170": {"UIF":"eyJlbWFpbCI6ImtsLmdyYW5kLmhvdGVsQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IlhiTVZVUllmVlNJQUhZSWlRMDRyV0EiLCJyb2xlIjoiT3duZXIiLCJpZCI6MjQ2NTU3NzU4LCJwaG9uZSI6IjkyNDgwMDM3MzgiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJmaXJzdF9uYW1lIjoiQW5rZXNoIiwic2V4IjoiTWFsZSIsInRlYW0iOiJNYXJrZXRpbmciLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTc2Mzk3ODgyMCIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ0NjkyNTczODQ5LCJhZGRyZXNzSnNvbiI6e319","UUID":"YzRlZWNmMzUtMTllNS00YjVhLTg4YTgtOGIwNGI2NzlkNWQ0","QID":83460},
    "HYD2984": {"UIF":"eyJlbWFpbCI6InByYXZlZW5hcHV0bHVyaTIwMDdAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiZ3FFMVg3RFhDR0RaeEhfQWdMWVpydyIsInJvbGUiOiJPd25lciIsImlkIjoyMTk1ODcyMjQsInBob25lIjoiODcxMjI5NjIxMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzQzMjQ1Mjc0IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5MjgzNTcxNDY5MDMsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"ZDY0ODFkMDgtYmVjZi00ZDU5LTgzZWItMmU1Y2U1NjMyMjEy","QID":299149},
    "HYD495": {"UIF":"eyJlbWFpbCI6Im1hbm9oYXJqb3NoQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IjJQMFVURk9lRElKdzZHejA0WlJMTHciLCJyb2xlIjoiT3duZXIiLCJpZCI6NDc0Mjk5MSwicGhvbmUiOiI5OTg1OTk4NTg4IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6IlZhcmFwcmFzYWRwbXByYXRhcCIsImxhc3RfbmFtZSI6IjgwOTY5OTQ0MjQiLCJjaXR5IjoiIiwic2V4IjoiTWFsZSIsInRlYW0iOiJPd25lciBFbmdhZ2VtZW50IiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwiYWRkcmVzcyI6IiIsInVwZGF0ZWRfYXQiOiIxNzYxOTgzODg1IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5NDYwNjAwMzI2MjgsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"YjAxMWE2MDgtMDc5Ni00OGZlLTliYjEtNDY0OWJkM2IzNzMx","QID":16711},
    "HYD2963": {"UIF":"eyJlbWFpbCI6InRoaXJ1cGF0aGlyYW90OEBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJrbS1UMGM0SVN0cU9fcW81dXlWeHZRIiwicm9sZSI6Ik93bmVyIiwiaWQiOjExMTEyMjI2MywicGhvbmUiOiI5NTAyMzIzNTEzIiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6InRhbmRyYSIsImxhc3RfbmFtZSI6InRpcnVwYXRoaXJhbyIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6IlRyYXZlbCBBZ2VudCIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsImFkZHJlc3MiOiIiLCJ1cGRhdGVkX2F0IjoiMTY2NjA5OTMzMyIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQxMTU1MDQ4NTA1LCJhZGRyZXNzSnNvbiI6e319","UUID":"MWE1OTRmY2ItOGQ0Ny00YTdlLWJhNDQtMTI4Yjk3OTI2OWY0","QID":296969},
    "HYD3183": {"UIF":"eyJlbWFpbCI6ImthbWFsYWFjaGFAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoia2RQTVZhV3ZVaGg1cTVaeTMxN3pKUSIsInJvbGUiOiJPd25lciIsImlkIjoyMTg0ODczNjEsInBob25lIjoiOTM5MTA0NDA3MSIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzQwNjUyMjIwIiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5NDA0NjU5NjU0MjYsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"YzA1YmE5ODItY2RhMy00MDhiLTk1NzQtNzMzMDA0NTZiM2Yw","QID":328327},
    "HYD1090": {"UIF":"eyJlbWFpbCI6InNoYW50aGFyZXNpZGVuY3lsb2RnZUBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJMV1d3VmxHOFhwRHVZQnBySXpkQkhnIiwicm9sZSI6Ik93bmVyIiwiaWQiOjIyMzI4MjUzNCwicGhvbmUiOiI4NTIwMDA1NDc5IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6Ikd1ZXN0Iiwic2V4IjoiTWFsZSIsInRlYW0iOiJNYXJrZXRpbmciLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTc0OTIxMjg3NyIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTMzNzUwNTgwMzk5LCJhZGRyZXNzSnNvbiI6e319","UUID":"Zjg4NDc3ZjgtMzM5Zi00ZmYwLWE2OGItYjdkMDEyOGQzNWJk","QID":78637},
    "HYD1762": {"UIF":"eyJlbWFpbCI6ImtlZXJ0aGljaGFuZHJhOTJAeWFob28uY29tIiwiYWNjZXNzX3Rva2VuIjoiUVF2QURDVmY3R3ZrUFB3Q3Q4SldNQSIsInJvbGUiOiJPd25lciIsImlkIjoxMTA1NjkzOTUsInBob25lIjoiOTk1OTY2NjYwMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJCYW5kYXJ1IiwibGFzdF9uYW1lIjoiVmVua2F0YXNhdHlha2VlcnRoaSIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6Ik93bmVyIEVuZ2FnZW1lbnQiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJhZGRyZXNzIjoiIiwidXBkYXRlZF9hdCI6IjE3MDczOTk3NTIiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk1MDM2MDg0MjM0NiwiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"M2Q4MzgxMmYtYzlhMS00NDVlLTk3MzUtZmFjMmQ3ODc0YTEx","QID":115451},
    "HYD588": {"UIF":"eyJlbWFpbCI6ImtlZXJ0aGljaGFuZHJhOTJAeWFob28uY29tIiwiYWNjZXNzX3Rva2VuIjoiUVF2QURDVmY3R3ZrUFB3Q3Q4SldNQSIsInJvbGUiOiJPd25lciIsImlkIjoxMTA1NjkzOTUsInBob25lIjoiOTk1OTY2NjYwMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJCYW5kYXJ1IiwibGFzdF9uYW1lIjoiVmVua2F0YXNhdHlha2VlcnRoaSIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6Ik93bmVyIEVuZ2FnZW1lbnQiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJhZGRyZXNzIjoiIiwidXBkYXRlZF9hdCI6IjE3MDczOTk3NTIiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk1MDM2MDg0MjM0NiwiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"M2Q4MzgxMmYtYzlhMS00NDVlLTk3MzUtZmFjMmQ3ODc0YTEx","QID":37182},
    "WAR144": {"UIF":"eyJlbWFpbCI6InZpc2hudWdyYW5kLmhhbmFta29uZGFAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiSUp5Q2dScWVBUHRrT1czMWRRcTJpZyIsInJvbGUiOiJPd25lciIsImlkIjoyMzcwNDQ0MjgsInBob25lIjoiNjMwMTg4ODg0MyIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzU0NTQ5MjEyIiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5Mzg3MTc2NDI1MjgsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"OWRhOTk1MjItNzZlMy00ZjkwLWFhODMtN2U3NTM1YzE4YzZi","QID":326437},
    "KMM030": {"UIF":"eyJlbWFpbCI6ImJsdWVtb29uaG90ZWwyNEBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJaRUtKbzBGWUpUNWROYWplOS1ocV9nIiwicm9sZSI6Ik93bmVyIiwiaWQiOjIwMzc1ODk1MywicGhvbmUiOiI5MTAwNzE4Mzg3IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwidXBkYXRlZF9hdCI6IjE3MjEzOTEzMzkiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjkyODMzNzE4MDMzMywiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"NzE2MGQxMDctNDliNS00YWE5LWI4MGMtY2E0ODQ1ZmZmNGIx","QID":244631},
    "NGA028": {"UIF":"eyJlbWFpbCI6ImtzYW5qZWV2YTlAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiX3FQZFdWSjNTeHNINVE3ZGs0S05xdyIsInJvbGUiOiJPd25lciIsImlkIjo3MjA4MjY4OCwicGhvbmUiOiI4NDk5ODgzMzExIiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6IkthbXNhbmkiLCJsYXN0X25hbWUiOiJTYW5qZWV2YSIsInRlYW0iOiJPcGVyYXRpb25zIiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwidXBkYXRlZF9hdCI6IjE3NjQ3NTc5NjIiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk0NzQyMTczMzQzMSwiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"NzRkNjcyMmEtNTU5Ni00NWM0LTk3NjQtNmFkZTVjODE5YjQ2","QID":353264},
}

PROPERTY_CHAT_IDS = {
    "HYD2857": -5187550502,
    "HYD2728": -5186344252,
    "HYD2927": -5116359155,
    "HYD3030": -5222836346,
    "HYD1170": -5286881526,
    "HYD1762": -5258058627,
    "HYD2984": -5212005817,
    "HYD495":  -5248899338,
    "HYD2963": -5043677128,
    "HYD3183": -5252188690,
    "WAR144":  -5203446779,
    "KMM030":  -5175487777,
    "HYD1090": -5235163232,
    "HYD588":  -5191559796,
    "NGA028":  -5298670289,
}

# =========================================================
# PERFORMANCE LIMITS
# =========================================================
PROP_PARALLEL_LIMIT = 5
DETAIL_PARALLEL_LIMIT = 10

prop_semaphore = asyncio.Semaphore(PROP_PARALLEL_LIMIT)
detail_semaphore = asyncio.Semaphore(DETAIL_PARALLEL_LIMIT)

HTTP: Optional[aiohttp.ClientSession] = None

CACHE: Dict[str, Any] = {}
CONFIRMED: Dict[str, Any] = {}
TG_OFFSET = 0

# ✅ super fast response cache (refreshed every 3 minutes)
PROPERTY_SNAPSHOT: Dict[str, Dict[str, Any]] = {}
SNAPSHOT_LAST_REFRESH = 0

# =========================================================
# CACHE HELPERS
# =========================================================
def cache_get(key: str):
    item = CACHE.get(key)
    if not item:
        return None
    if time.time() > item["exp"]:
        return None
    return item["val"]

def cache_set(key: str, val: Any, ttl: int = 60):
    CACHE[key] = {"val": val, "exp": time.time() + ttl}

# =========================================================
# GEO / DISTANCE
# =========================================================
def haversine_km(lat1, lon1, lat2, lon2):
    try:
        R = 6371
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl/2)**2
        return 2 * R * math.asin(math.sqrt(a))
    except Exception:
        return 999999

async def geocode_free(query: str) -> Optional[Tuple[float, float]]:
    q = (query or "").strip()
    if not q:
        return None

    ck = f"geo:{q.lower()}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "limit": 1}
    headers = {"User-Agent": "HotelBooking/1.0 (admin)"}

    try:
        async with HTTP.get(url, params=params, headers=headers, timeout=15) as r:
            if r.status != 200:
                return None
            data = await r.json()
            if not data:
                return None
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            cache_set(ck, (lat, lon), 3600)
            return lat, lon
    except Exception:
        return None

# =========================================================
# EMAIL
# =========================================================
def send_email(to_email: str, subject: str, body: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and SMTP_FROM):
        return

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=ctx)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

def build_request_id(prop_code: str, room: str):
    return f"BR-{int(time.time())}-{prop_code}-{room}"

# =========================================================
# TELEGRAM SEND
# =========================================================
async def tg_send(chat_id: int, text: str, reply_markup: dict = None):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with HTTP.post(url, json=payload, timeout=25) as r:
        data = await r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram send failed: {data}")
        return data

# =========================================================
# OYO APIs
# =========================================================
async def fetch_property_details(P: Dict[str, Any]) -> Dict[str, Any]:
    ck = f"prop_details:{P['QID']}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    url = "https://www.oyoos.com/hms_ms/api/v1/location/property-details"
    params = {"qid": P["QID"]}
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    for attempt in range(1, 4):
        try:
            async with HTTP.get(url, params=params, cookies=cookies, headers=headers, timeout=20) as r:
                if r.status != 200:
                    raise RuntimeError(f"property-details API failed {r.status}")
                data = await r.json()

                out = {
                    "name": str(data.get("name", "") or "").strip(),
                    "alternate_name": str(data.get("alternate_name", "") or "").strip(),
                    "plot_number": str(data.get("plot_number", "") or "").strip(),
                    "street": str(data.get("street", "") or "").strip(),
                    "pincode": str(data.get("pincode", "") or "").strip(),
                    "city": str(data.get("city", "") or "").strip(),
                    "country": str(data.get("country", "") or "").strip(),
                    "map_link": str(data.get("map_link", "") or "").strip(),
                    "latitude": data.get("latitude", None),
                    "longitude": data.get("longitude", None),
                }
                cache_set(ck, out, 3600)
                return out
        except Exception:
            await asyncio.sleep(1 + attempt)

    out = {
        "name": "", "alternate_name": "", "plot_number": "", "street": "",
        "pincode": "", "city": "", "country": "", "map_link": "",
        "latitude": None, "longitude": None,
    }
    cache_set(ck, out, 300)
    return out

async def fetch_rooms(P: Dict[str, Any]) -> List[Dict[str, str]]:
    ck = f"rooms:{P['QID']}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    url = "https://www.oyoos.com/hms_ms/api/v1/hotels/roomsNew"
    params = {"qid": P["QID"]}
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    for attempt in range(1, 4):
        try:
            async with HTTP.get(url, params=params, cookies=cookies, headers=headers, timeout=25) as r:
                if r.status != 200:
                    raise RuntimeError(f"roomsNew failed {r.status}")
                data = await r.json()
                rooms_obj = data.get("rooms", {}) or {}

                rooms: List[Dict[str, str]] = []
                for rm in rooms_obj.values():
                    rn = rm.get("room_number") or rm.get("roomNumber") or rm.get("number")
                    if rn is None:
                        continue

                    floor = rm.get("floor") or rm.get("floor_number") or rm.get("floorNumber")
                    if not floor:
                        s = str(rn)
                        floor = s[0] if s and s[0].isdigit() else "1"

                    rooms.append({
                        "room": str(rn),
                        "floor": str(floor),
                        "type": str(rm.get("room_type_name") or rm.get("type") or "Standard")
                    })

                cache_set(ck, rooms, 300)
                return rooms
        except Exception:
            await asyncio.sleep(1 + attempt)

    cache_set(ck, [], 60)
    return []

async def fetch_booking_details_rooms(P: Dict[str, Any], booking_id: str) -> List[str]:
    url = "https://www.oyoos.com/hms_ms/api/v1/visibility/booking_details_with_entities"
    params = {
        "qid": P["QID"],
        "booking_id": booking_id,
        "role": 0,
        "platform": "OYOOS",
        "country_code": 1
    }
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    async with detail_semaphore:
        try:
            async with HTTP.get(url, params=params, cookies=cookies, headers=headers, timeout=25) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                stay = (data.get("entities", {}) or {}).get("stayDetails", {}) or {}
                rooms = []
                for s in stay.values():
                    rn = s.get("room_number")
                    if rn:
                        rooms.append(str(rn))
                return rooms
        except Exception:
            return []

# =========================================================
# ✅ IN-HOUSE BOOKING FILTER (YOUR CONFIRMED LOGIC)
# status must be Checked In
# active-date condition:
# if not (ci <= target_dt <= co or (ci == tf_date+1 and target_dt <= co)) continue
# =========================================================
def _active_inhouse_booking(status: str, ci: datetime, co: datetime, target_dt: datetime, tf_date: datetime) -> bool:
    if status != "Checked In":
        return False
    if not (ci <= target_dt <= co or (ci == tf_date + timedelta(days=1) and target_dt <= co)):
        return False
    return True

# =========================================================
# PRECISE BOOKED ROOMS FOR WINDOW
# =========================================================
async def fetch_booked_rooms_precise(P: Dict[str, Any], start_date: str, end_date: str) -> Set[str]:
    """
    booking list -> booking details -> room numbers
    Uses Checked In only (your in-house correct logic)
    """
    ck = f"booked:{P['QID']}:{start_date}:{end_date}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    url = "https://www.oyoos.com/hms_ms/api/v1/get_booking_with_ids"
    params = {
        "qid": P["QID"],
        "checkin_from": start_date,
        "checkin_till": end_date,
        "batch_count": 100,
        "batch_offset": 0,
        "visibility_required": "true",
        "additionalParams": "guest,stay_details",
        "decimal_price": "true",
        "ascending": "true",
        "sort_on": "checkin_date"
    }
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    booked: Set[str] = set()
    try:
        async with HTTP.get(url, params=params, cookies=cookies, headers=headers, timeout=30) as r:
            if r.status != 200:
                cache_set(ck, booked, 30)
                return booked
            data = await r.json()
            bookings = (data.get("entities", {}) or {}).get("bookings", {}) or {}

            target_dt = datetime.strptime(start_date, "%Y-%m-%d")
            tf_date = target_dt  # for your logic

            booking_ids = []
            for b in bookings.values():
                status = (b.get("status") or "").strip()
                ci_s = str(b.get("checkin") or "").strip()
                co_s = str(b.get("checkout") or "").strip()
                if not ci_s or not co_s:
                    continue
                try:
                    ci = datetime.strptime(ci_s, "%Y-%m-%d")
                    co = datetime.strptime(co_s, "%Y-%m-%d")
                except Exception:
                    continue

                if not _active_inhouse_booking(status, ci, co, target_dt, tf_date):
                    continue

                bid = str(b.get("booking_no") or "").strip()
                if bid:
                    booking_ids.append(bid)

            tasks = [fetch_booking_details_rooms(P, bid) for bid in booking_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    continue
                for rn in res:
                    booked.add(str(rn))

        cache_set(ck, booked, 60)
        return booked
    except Exception:
        cache_set(ck, booked, 30)
        return booked

# =========================================================
# ✅ AVAILABLE ROOMS
# =========================================================
async def count_available_rooms(P: Dict[str, Any], from_: str, to: str) -> int:
    rooms = await fetch_rooms(P)
    total_rooms = len(rooms)

    ck = f"avail_precise:{P['QID']}:{from_}:{to}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    booked_rooms = await fetch_booked_rooms_precise(P, from_, to)
    available = max(total_rooms - len(booked_rooms), 0)

    cache_set(ck, available, 60)
    return available

# =========================================================
# ROOM STANDARD PRICE LOGIC
# highest per-day price from last 10 bookings of that room
# =========================================================
async def compute_room_standard_prices(P: Dict[str, Any], prop_code: str, room_numbers: List[str]) -> Dict[str, int]:
    """
    For each room:
      - scan bookings in last 90 days
      - find bookings containing that room
      - take last 10 matches
      - compute per-day amount (paid + balance)/stay
      - standard price = highest per-day among last 10
    """
    ck = f"room_prices:{prop_code}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    # History range fixed: 90 days to today
    today = datetime.now().date()
    hf = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    ht = today.strftime("%Y-%m-%d")

    url = "https://www.oyoos.com/hms_ms/api/v1/get_booking_with_ids"
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    # store list of per-day prices per room (keep last 10)
    prices: Dict[str, List[float]] = {rn: [] for rn in room_numbers}

    offset = 0
    try:
        while True:
            params = {
                "qid": P["QID"],
                "checkin_from": hf,
                "checkin_till": ht,
                "batch_count": 100,
                "batch_offset": offset,
                "visibility_required": "true",
                "additionalParams": "payment_hold_transaction,guest,stay_details",
                "decimal_price": "true",
                "ascending": "false",
                "sort_on": "checkin_date"
            }

            async with HTTP.get(url, params=params, cookies=cookies, headers=headers, timeout=35) as r:
                if r.status != 200:
                    break
                data = await r.json()
                booking_ids = data.get("bookingIds") or []
                bookings = (data.get("entities", {}) or {}).get("bookings", {}) or {}
                if not bookings:
                    break

                # iterate bookings newest first
                for b in bookings.values():
                    bid = str(b.get("booking_no") or "").strip()
                    if not bid:
                        continue

                    ci_s = str(b.get("checkin") or "").strip()
                    co_s = str(b.get("checkout") or "").strip()
                    if not ci_s or not co_s:
                        continue

                    try:
                        ci = datetime.strptime(ci_s, "%Y-%m-%d")
                        co = datetime.strptime(co_s, "%Y-%m-%d")
                    except Exception:
                        continue

                    stay = max((co - ci).days, 1)
                    paid = float(b.get("get_amount_paid") or 0.0)
                    balance = float(b.get("payable_amount") or 0.0)
                    total_amt = paid + balance
                    per_day = total_amt / stay

                    # fetch rooms for this booking
                    rms = await fetch_booking_details_rooms(P, bid)
                    if not rms:
                        continue

                    for rn in rms:
                        if rn in prices:
                            prices[rn].append(per_day)
                            # keep last 10 only
                            if len(prices[rn]) > 10:
                                prices[rn] = prices[rn][-10:]

                if len(booking_ids) < 100:
                    break
                offset += 100

        # compute standard price (highest of last 10)
        out: Dict[str, int] = {}
        for rn in room_numbers:
            lst = prices.get(rn) or []
            if not lst:
                out[rn] = 0
            else:
                out[rn] = int(max(lst))

        cache_set(ck, out, 180)  # refresh every 3 minutes
        return out

    except Exception:
        out = {rn: 0 for rn in room_numbers}
        cache_set(ck, out, 120)
        return out

# =========================================================
# SNAPSHOT REFRESH (every 3 minutes)
# =========================================================
async def refresh_all_snapshots_once():
    await refresh_all_snapshots()


async def refresh_all_snapshots_loop():
    global PROPERTY_SNAPSHOT, SNAPSHOT_LAST_REFRESH
    await asyncio.sleep(2)

    while True:
        try:
            start = time.time()
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            async def one_prop(code: str, P: Dict[str, Any]):
                async with prop_semaphore:
                    d = await fetch_property_details(P)
                    rooms = await fetch_rooms(P)
                    available = await count_available_rooms(P, today, tomorrow)

                    address = " ".join([
                        d.get("plot_number", ""),
                        d.get("street", ""),
                        d.get("city", ""),
                        d.get("pincode", "")
                    ]).strip()

                    name = d.get("alternate_name") or d.get("name") or code

                    # compute property today price = least standard price among rooms
                    room_nums = [r["room"] for r in rooms]
                    room_prices = await compute_room_standard_prices(P, code, room_nums)
                    least_price = 0
                    try:
                        vals = [v for v in room_prices.values() if v > 0]
                        least_price = min(vals) if vals else 0
                    except Exception:
                        least_price = 0

                    return code, {
                        "code": code,
                        "name": name,
                        "address": address,
                        "city": d.get("city", ""),
                        "pincode": d.get("pincode", ""),
                        "map_link": d.get("map_link", ""),
                        "latitude": d.get("latitude", None),
                        "longitude": d.get("longitude", None),
                        "today_price": int(least_price),   # ✅ property Today Price (least room price)
                        "available_rooms": int(available),
                        "updated_at": int(time.time())
                    }

            tasks = [one_prop(code, P) for code, P in PROPERTIES.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            snap: Dict[str, Dict[str, Any]] = {}
            for r in results:
                if isinstance(r, Exception):
                    continue
                code, payload = r
                snap[code] = payload

            if snap:
                PROPERTY_SNAPSHOT = snap
                SNAPSHOT_LAST_REFRESH = int(time.time())

            took = round(time.time() - start, 2)
            print(f"✅ SNAPSHOT REFRESH DONE: {len(PROPERTY_SNAPSHOT)} properties in {took}s")

        except Exception as e:
            print("❌ SNAPSHOT REFRESH FAILED:", e)

        await asyncio.sleep(180)  # ✅ every 3 minutes

# =========================================================
# TELEGRAM POLLING LOOP
# =========================================================
async def tg_polling_loop():
    global TG_OFFSET
    if not BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN missing. Polling disabled.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    while True:
        try:
            params = {"timeout": 30, "offset": TG_OFFSET}
            async with HTTP.get(url, params=params, timeout=35) as r:
                data = await r.json()
                if not data.get("ok"):
                    await asyncio.sleep(3)
                    continue

                updates = data.get("result", [])
                for u in updates:
                    TG_OFFSET = max(TG_OFFSET, int(u.get("update_id", 0)) + 1)

                    cb = u.get("callback_query")
                    if not cb:
                        continue

                    cb_data = str(cb.get("data") or "")
                    if "|" not in cb_data:
                        continue

                    action, request_id = cb_data.split("|", 1)
                    booking = CONFIRMED.get(request_id)
                    if not booking:
                        continue

                    chat_id = cb["message"]["chat"]["id"]

                    if action == "CONFIRM":
                        booking["status"] = "confirmed"
                        CONFIRMED[request_id] = booking
                        await tg_send(chat_id, f"✅ CONFIRMED <code>{request_id}</code>")

                        try:
                            if booking.get("email"):
                                send_email(
                                    booking["email"],
                                    "Booking Confirmed",
                                    f"✅ Your booking is CONFIRMED.\n\n"
                                    f"Property: {booking['property_code']}\n"
                                    f"Room: {booking['room']}\n"
                                    f"Dates: {booking['from']} to {booking['to']}\n"
                                    f"Request ID: {request_id}\n"
                                )
                        except Exception:
                            pass

                    elif action == "REJECT":
                        booking["status"] = "rejected"
                        CONFIRMED[request_id] = booking
                        await tg_send(chat_id, f"❌ REJECTED <code>{request_id}</code>")

                        try:
                            if booking.get("email"):
                                send_email(
                                    booking["email"],
                                    "Booking Not Confirmed",
                                    f"❌ Your booking could not be confirmed.\n\n"
                                    f"Property: {booking['property_code']}\n"
                                    f"Room: {booking['room']}\n"
                                    f"Dates: {booking['from']} to {booking['to']}\n"
                                    f"Request ID: {request_id}\n"
                                )
                        except Exception:
                            pass

        except Exception:
            await asyncio.sleep(2)

# =========================================================
# STARTUP / SHUTDOWN
# =========================================================
@app.on_event("startup")
async def on_startup():
    global HTTP
    if HTTP is None:
        timeout = aiohttp.ClientTimeout(total=45)
        connector = aiohttp.TCPConnector(limit=60, ttl_dns_cache=300)
        HTTP = aiohttp.ClientSession(timeout=timeout, connector=connector)

    asyncio.create_task(tg_polling_loop())
    if os.getenv("AUTO_SYNC_ON_STARTUP", "0").strip() == "1":
        asyncio.create_task(refresh_all_snapshots_loop())

@app.on_event("shutdown")
async def on_shutdown():
    global HTTP
    if HTTP:
        await HTTP.close()
        HTTP = None

# =========================================================
# ROUTES
# =========================================================

# -----------------------------
# Admin Pages (same design language)
# -----------------------------
BASE_DIR = os.path.dirname(__file__)

def _read_html_file(name: str) -> str:
    p = os.path.join(BASE_DIR, name)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _require_admin(request: Request):
    c = request.cookies.get("admin_session", "")
    if not c or not _verify_session(c):
        return False
    return True

@app.get("/admin")
async def admin_login_page():
    return HTMLResponse(_read_html_file("admin.html"))

@app.post("/admin/login")
async def admin_login(request: Request):
    form = await request.form()
    u = (form.get("username") or "").strip()
    p = (form.get("password") or "").strip()
    if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
        resp = RedirectResponse(url="/admin/dashboard", status_code=302)
        resp.set_cookie("admin_session", _make_session(u), httponly=True, samesite="lax")
        return resp
    return HTMLResponse(_read_html_file("admin.html").replace("{{ERROR}}", "Invalid credentials"), status_code=401)

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    if not _require_admin(request):
        return RedirectResponse(url="/admin", status_code=302)
    html = _read_html_file("admin_dashboard.html")
    return HTMLResponse(html)

@app.post("/admin/logout")
async def admin_logout():
    resp = RedirectResponse(url="/admin", status_code=302)
    resp.delete_cookie("admin_session")
    return resp

# -------- Admin APIs (GitHub-backed) ----------
@app.get("/admin/api/overrides")
async def admin_get_overrides(request: Request):
    if not _require_admin(request):
        return JSONResponse({"error":"unauthorized"}, status_code=401)
    prices_over, status_over = load_overrides()
    return {"prices": prices_over, "room_status": status_over}

@app.post("/admin/api/save-prices")
async def admin_save_prices(request: Request):
    if not _require_admin(request):
        return JSONResponse({"error":"unauthorized"}, status_code=401)
    payload = await request.json()
    prices = payload.get("prices") or {}
    _write_json(PRICES_FILE, prices)
    await _github_commit_file("data/admin_prices.json", json.dumps(prices, indent=2).encode("utf-8"), "Admin: update prices")
    return {"ok": True}

@app.post("/admin/api/save-room-status")
async def admin_save_room_status(request: Request):
    if not _require_admin(request):
        return JSONResponse({"error":"unauthorized"}, status_code=401)
    payload = await request.json()
    statuses = payload.get("room_status") or {}
    _write_json(ROOM_STATUS_FILE, statuses)
    await _github_commit_file("data/admin_room_status.json", json.dumps(statuses, indent=2).encode("utf-8"), "Admin: update room status")
    return {"ok": True}

@app.post("/admin/api/sync")
async def admin_sync_now(request: Request):
    if not _require_admin(request):
        return JSONResponse({"error":"unauthorized"}, status_code=401)
    # Only trigger the existing sync logic once
    await refresh_all_snapshots_once()
    return {"ok": True, "snapshot_time": SNAPSHOT_LAST_REFRESH}


@app.get("/api/health")
async def health():
    return {"ok": True, "time": int(time.time())}

@app.get("/api/search")
async def search(location: str = "", from_: str = "", to: str = ""):
    """
    ✅ Ultra fast: return from snapshot, compute distance only.
    """
    loc = (location or "").strip()
    user_geo = await geocode_free(loc) if loc else None

    hotels = list(PROPERTY_SNAPSHOT.values()) if PROPERTY_SNAPSHOT else []
    prices_over, status_over = load_overrides()
    for h in hotels:
        apply_admin_overrides_to_property(h, prices_over, status_over)

    if user_geo:
        for h in hotels:
            lat = h.get("latitude")
            lon = h.get("longitude")
            if lat is not None and lon is not None:
                h["distance_km"] = round(haversine_km(user_geo[0], user_geo[1], float(lat), float(lon)), 2)
            else:
                h["distance_km"] = None
        hotels.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 999999))
    else:
        for h in hotels:
            h["distance_km"] = None

    return {"hotels": hotels, "snapshot_time": SNAPSHOT_LAST_REFRESH, "company": COMPANY_NAME}

@app.get("/api/property/{code}")
async def property_details(code: str, from_: str = "", to: str = ""):
    P = PROPERTIES.get(code)
    if not P:
        return JSONResponse({"error": "Invalid property"}, status_code=404)

    if not from_:
        from_ = datetime.now().strftime("%Y-%m-%d")
    if not to:
        to = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    d = await fetch_property_details(P)
    rooms = await fetch_rooms(P)

    booked_rooms = await fetch_booked_rooms_precise(P, from_, to)

    floors = sorted({r["floor"] for r in rooms}) or ["1"]

    # compute room standard prices
    room_nums = [r["room"] for r in rooms]
    room_prices = await compute_room_standard_prices(P, code, room_nums)

    out_rooms = []
    for r in rooms:
        rn = r["room"]
        status = "booked" if rn in booked_rooms else "available"
        std_price = int(room_prices.get(rn, 0) or 0)
        images = list_room_images(code, rn)
        out_rooms.append({**r, "status": status, "standard_price": std_price, "images": images})

    address = " ".join([
        d.get("plot_number", ""),
        d.get("street", ""),
        d.get("city", ""),
        d.get("pincode", "")
    ]).strip()

    # property today price = least standard price among rooms
    least_price = 0
    try:
        vals = [int(room_prices.get(rn, 0) or 0) for rn in room_nums]
        vals = [v for v in vals if v > 0]
        least_price = min(vals) if vals else 0
    except Exception:
        least_price = 0

    prices_over, status_over = load_overrides()
    prop_obj = {"code": code, "rooms": out_rooms, "today_price": int(least_price), "standard_price": int(least_price)}
    apply_admin_overrides_to_property(prop_obj, prices_over, status_over)
    # apply overrides back
    least_price = prop_obj.get("today_price", int(least_price))
    out_rooms = prop_obj.get("rooms", out_rooms)

    return {
        "code": code,
        "name": d.get("alternate_name") or d.get("name") or code,
        "address": address,
        "map_link": d.get("map_link", ""),
        "latitude": d.get("latitude", None),
        "longitude": d.get("longitude", None),

        # ✅ keep field name for frontend (today price)
        "today_price": int(least_price),
        "standard_price": int(least_price),
        # Backward compat for existing frontend JS
        "yesterday_arr": int(least_price),

        "floors": floors,
        "rooms": out_rooms,
        "company": COMPANY_NAME
    }

@app.get("/api/room-images/{code}/{room}")
async def api_room_images(code: str, room: str):
    """
    Used by frontend View Room button to load images dynamically.
    """
    imgs = list_room_images(code, room)
    return {"code": code, "room": room, "images": imgs}

@app.post("/api/book")
async def book(req: Request):
    data = await req.json()

    prop = str(data.get("property_code") or "").strip()
    room = str(data.get("room") or "").strip()
    from_ = str(data.get("from") or "").strip()
    to = str(data.get("to") or "").strip()

    if not prop or not room or not from_ or not to:
        return JSONResponse({"ok": False, "error": "Missing fields"}, status_code=400)

    if prop not in PROPERTIES:
        return JSONResponse({"ok": False, "error": "Invalid property"}, status_code=400)

    chat_id = PROPERTY_CHAT_IDS.get(prop)
    if not chat_id:
        return JSONResponse({"ok": False, "error": "Telegram group not mapped"}, status_code=400)

    request_id = build_request_id(prop, room)

    CONFIRMED[request_id] = {
        **data,
        "request_id": request_id,
        "status": "requested",
        "created_at": int(time.time())
    }

    text = (
        f"<b>🛎️ NEW BOOKING REQUEST</b>\n"
        f"<b>🏢 Property:</b> {prop}\n"
        f"<b>🏠 Room:</b> {room}\n"
        f"<b>📅 From:</b> {from_}\n"
        f"<b>📅 To:</b> {to}\n\n"
        f"<b>👤 Name:</b> {data.get('name')}\n"
        f"<b>📞 Phone:</b> {data.get('phone')}\n"
        f"<b>📧 Email:</b> {data.get('email')}\n"
        f"<b>📍 Address:</b> {data.get('address') or '-'}\n\n"
        f"<b>Request ID:</b> <code>{request_id}</code>"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Confirm", "callback_data": f"CONFIRM|{request_id}"},
            {"text": "❌ Reject", "callback_data": f"REJECT|{request_id}"}
        ]]
    }

    await tg_send(chat_id, text, reply_markup=keyboard)

    try:
        if data.get("email"):
            send_email(
                data["email"],
                "Booking Request Received",
                f"Your booking request is received.\n\n"
                f"Property: {prop}\n"
                f"Room: {room}\n"
                f"Dates: {from_} to {to}\n"
                f"Request ID: {request_id}\n\n"
                f"Our team will call you soon to confirm."
            )
    except Exception:
        pass

    return {"ok": True, "request_id": request_id}
