import os, time, math, asyncio, ssl, smtplib
from email.message import EmailMessage
from typing import Dict, Any, Optional, Tuple, List, Set

import aiohttp
from dotenv import load_dotenv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
# FASTAPI
# =========================================================
app = FastAPI(title="Hotel Booking API - Production (OYO + Telegram)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# PROPERTIES
# =========================================================
PROPERTIES: Dict[str, Dict[str, Any]] = {
    "HYD2857": {"UIF":"eyJlbWFpbCI6Im1vaGRzdWFpZGFobWVkQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6Im51QmI0XzNlREJPWjRaVGxLdlFsMXciLCJyb2xlIjoiT3duZXIiLCJpZCI6MjAzMzEzMjUyLCJwaG9uZSI6Ijk5ODUyODMzMDYiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTczMjI2MTE0MiIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ5MTExOTU1NDQzLCJhZGRyZXNzSnNvbiI6e319","UUID":"NGY2ZGI1NjYtNzEyZS00MTI3LTljM2MtMmM5MDVjYjdkMWZk","QID":259690},
    "HYD2728": {"UIF":"eyJlbWFpbCI6ImNoZWYubml0aW5AZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiZm11QjhxREVCQjJfbzRfSW1tQ0NqUSIsInJvbGUiOiJPd25lciIsImlkIjoyMDQ3MjI0OTMsInBob25lIjoiOTEwMDA5MjU4NiIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzIwNzkzNTg3IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3JfcGFzc3dvcmRfZXhwaXJ5Ijo5MTY4ODQ3NzQ1MzQsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"NmYxMzY0NmUtNWM0ZC00ZWUyLWFkZWEtMDFkZTMyZmM3ZjRm","QID":245844},
    "HYD2927": {"UIF":"eyJlbWFpbCI6InVwcGFsYXNhaTg4QGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IlVCTjcxVDB0aFJlZXZpemxRbEVrbmciLCJyb2xlIjoiT3duZXIiLCJpZCI6MjE2Mzk4NDcwLCJwaG9uZSI6Ijg2ODYwNjY2NjYiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTczNzc4NTUxNCIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ4NzI2ODk5NDY3LCJhZGRyZXNzSnNvbiI6e319","UUID":"ODczOWYwMzMtYzQ5YS00NTRkLWFhNWUtNTJmOTdmYjQ3OWNj","QID":292909},
    "HYD3030": {"UIF":"eyJlbWFpbCI6InN2aG90ZWw5OTlAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoic2x5Y2Fta0pBbU9uZUt2SXlwOWVsUSIsInJvbGUiOiJPd25lciIsImlkIjoyMzU5NTMyNTAsInBob25lIjoiOTk4NTM0NzQ3NiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJHdWVzdCIsInNleCI6Ik1hbGUiLCJ0ZWFtIjoiTWFya2V0aW5nIiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwidXBkYXRlZF9hdCI6IjE3NTM4ODQzOTEiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk0MDI5NDU3MjI0MywiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"ZjNjZmZkMWQtOTJiMS00ZjM3LWE1YWMtZGQ3NGExNGIwN2Q5","QID":304236},
    "HYD1170": {"UIF":"eyJlbWFpbCI6ImtsLmdyYW5kLmhvdGVsQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IlhiTVZVUllmVlNJQUhZSWlRMDRyV0EiLCJyb2xlIjoiT3duZXIiLCJpZCI6MjQ2NTU3NzU4LCJwaG9uZSI6IjkyNDgwMDM3MzgiLCJjb3VudHJ5X2NvZGUiOiIrOTEiLCJmaXJzdF9uYW1lIjoiQW5rZXNoIiwic2V4IjoiTWFsZSIsInRlYW0iOiJNYXJrZXRpbmciLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTc2Mzk3ODgyMCIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQ0NjkyNTczODQ5LCJhZGRyZXNzSnNvbiI6e319","UUID":"YzRlZWNmMzUtMTllNS00YjVhLTg4YTgtOGIwNGI2NzlkNWQ0","QID":83460},
    "HYD1762": {"UIF":"eyJlbWFpbCI6ImtlZXJ0aGljaGFuZHJhOTJAeWFob28uY29tIiwiYWNjZXNzX3Rva2VuIjoibWNCYlEzUUhxZGtRSUYtWUU0X3d0dyIsInJvbGUiOiJPd25lciIsImlkIjoxMTA1NjkzOTUsInBob25lIjoiOTk1OTY2NjYwMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJCYW5kYXJ1IiwibGFzdF9uYW1lIjoiVmVua2F0YXNhdHlha2VlcnRoaSIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6Ik93bmVyIEVuZ2FnZW1lbnQiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJhZGRyZXNzIjoiIiwidXBkYXRlZF9hdCI6IjE3MDczOTk3NTIiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk0NjkyMjA2NjUxOCwiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"ZjMwZmZlNTgtYTlkNi00NDEzLTlmM2UtY2E5MWI1NTU4ZWUw","QID":115451},
    "HYD2984": {"UIF":"eyJlbWFpbCI6InByYXZlZW5hcHV0bHVyaTIwMDdAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiZ3FFMVg3RFhDR0RaeEhfQWdMWVpydyIsInJvbGUiOiJPd25lciIsImlkIjoyMTk1ODcyMjQsInBob25lIjoiODcxMjI5NjIxMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzQzMjQ1Mjc0IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3J_fcGFzc3dvcmRfZXhwaXJ5Ijo5MjgzNTcxNDY5MDMsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"ZDY0ODFkMDgtYmVjZi00ZDU5LTgzZWItMmU1Y2U1NjMyMjEy","QID":299149},
    "HYD495": {"UIF":"eyJlbWFpbCI6Im1hbm9oYXJqb3NoQGdtYWlsLmNvbSIsImFjY2Vzc190b2tlbiI6IjJQMFVURk9lRElKdzZHejA0WlJMTHciLCJyb2xlIjoiT3duZXIiLCJpZCI6NDc0Mjk5MSwicGhvbmUiOiI5OTg1OTk4NTg4IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6IlZhcmFwcmFzYWRwbXByYXRhcCIsImxhc3RfbmFtZSI6IjgwOTY5OTQ0MjQiLCJjaXR5IjoiIiwic2V4IjoiTWFsZSIsInRlYW0iOiJPd25lciBFbmdhZ2VtZW50IiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwiYWRkcmVzcyI6IiIsInVwZGF0ZWRfYXQiOiIxNzYxOTgzODg1IiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3J_fcGFzc3dvcmRfZXhwaXJ5Ijo5NDYwNjAwMzI2MjgsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"YjAxMWE2MDgtMDc5Ni00OGZlLTliYjEtNDY0OWJkM2IzNzMx","QID":16711},
    "HYD2963": {"UIF":"eyJlbWFpbCI6InRoaXJ1cGF0aGlyYW90OEBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJrbS1UMGM0SVN0cU9fcW81dXlWeHZRIiwicm9sZSI6Ik93bmVyIiwiaWQiOjExMTEyMjI2MywicGhvbmUiOiI5NTAyMzIzNTEzIiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6InRhbmRyYSIsImxhc3RfbmFtZSI6InRpcnVwYXRoaXJhbyIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6IlRyYXZlbCBBZ2VudCIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsImFkZHJlc3MiOiIiLCJ1cGRhdGVkX2F0IjoiMTY2NjA5OTMzMyIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGUiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTQxMTU1MDQ4NTA1LCJhZGRyZXNzSnNvbiI6e319","UUID":"MWE1OTRmY2ItOGQ0Ny00YTdlLWJhNDQtMTI4Yjk3OTI2OWY0","QID":296969},
    "HYD3183": {"UIF":"eyJlbWFpbCI6ImthbWFsYWFjaGFAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoia2RQTVZhV3ZVaGg1cTVaeTMxN3pKUSIsInJvbGUiOiJPd25lciIsImlkIjoyMTg0ODczNjEsInBob25lIjoiOTM5MTA0NDA3MSIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzQwNjUyMjIwIiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3J_fcGFzc3dvcmRfZXhwaXJ5Ijo5NDA0NjU5NjU0MjYsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"YzA1YmE5ODItY2RhMy00MDhiLTk1NzQtNzMzMDA0NTZiM2Yw","QID":328327},
    "WAR144": {"UIF":"eyJlbWFpbCI6InZpc2hudWdyYW5kLmhhbmFta29uZGFAZ21haWwuY29tIiwiYWNjZXNzX3Rva2VuIjoiSUp5Q2dScWVBUHRrT1czMWRRcTJpZyIsInJvbGUiOiJPd25lciIsImlkIjoyMzcwNDQ0MjgsInBob25lIjoiNjMwMTg4ODg0MyIsImNvdW50cnlfY29kZSI6Iis5MSIsImRldmlzZV9yb2xlIjoiT3duZXJfUG9ydGFsX1VzZXIiLCJwaG9uZV92ZXJpZmllZCI6dHJ1ZSwiZW1haWxfdmVyaWZpZWQiOnRydWUsInVwZGF0ZWRfYXQiOiIxNzU0NTQ5MjEyIiwiZmVhdHVyZXMiOnt9LCJzdGF0dXNfY29kZSI6MTAwLCJtaWxsaXNfbGVmdF9mb3J_fcGFzc3dvcmRfZXhwaXJ5Ijo5Mzg3MTc2NDI1MjgsImFkZHJlc3NKc29uIjp7fX0%3D","UUID":"OWRhOTk1MjItNzZlMy00ZjkwLWFhODMtN2U3NTM1YzE4YzZi","QID":326437},
    "KMM030": {"UIF":"eyJlbWFpbCI6ImJsdWVtb29uaG90ZWwyNEBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJaRUtKbzBGWUpUNWROYWplOS1ocV9nIiwicm9sZSI6Ik93bmVyIiwiaWQiOjIwMzc1ODk1MywicGhvbmUiOiI5MTAwNzE4Mzg3IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZGV2aXNlX3JvbGUiOiJPd25lcl9Qb3J0YWxfVXNlciIsInBob25lX3ZlcmlmaWVkIjp0cnVlLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwidXBkYXRlZF9hdCI6IjE3MjEzOTEzMzkiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjkyODMzNzE4MDMzMywiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"NzE2MGQxMDctNDliNS00YWE5LWI4MGMtY2E0ODQ1ZmZmNGIx","QID":244631},
    "HYD1090": {"UIF":"eyJlbWFpbCI6InNoYW50aGFyZXNpZGVuY3lsb2RnZUBnbWFpbC5jb20iLCJhY2Nlc3NfdG9rZW4iOiJMV1d3VmxHOFhwRHVZQnBySXpkQkhnIiwicm9sZSI6Ik93bmVyIiwiaWQiOjIyMzI4MjUzNCwicGhvbmUiOiI4NTIwMDA1NDc5IiwiY291bnRyeV9jb2RlIjoiKzkxIiwiZmlyc3RfbmFtZSI6Ikd1ZXN0Iiwic2V4IjoiTWFsZSIsInRlYW0iOiJNYXJrZXRpbmciLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJ1cGRhdGVkX2F0IjoiMTc0OTIxMjg3NyIsImZlYXR1cmVzIjp7fSwic3RhdHVzX2NvZGQiOjEwMCwibWlsbGlzX2xlZnRfZm9yX3Bhc3N3b3JkX2V4cGlyeSI6OTMzNzUwNTgwMzk5LCJhZGRyZXNzSnNvbiI6e319","UUID":"Zjg4NDc3ZjgtMzM5Zi00ZmYwLWE2OGItYjdkMDEyOGQzNWJk","QID":78637},
    "HYD588": {"UIF":"eyJlbWFpbCI6ImtlZXJ0aGljaGFuZHJhOTJAeWFob28uY29tIiwiYWNjZXNzX3Rva2VuIjoibWNCYlEzUUhxZGtRSUYtWUU0X3d0dyIsInJvbGUiOiJPd25lciIsImlkIjoxMTA1NjkzOTUsInBob25lIjoiOTk1OTY2NjYwMiIsImNvdW50cnlfY29kZSI6Iis5MSIsImZpcnN0X25hbWUiOiJCYW5kYXJ1IiwibGFzdF9uYW1lIjoiVmVua2F0YXNhdHlha2VlcnRoaSIsImNpdHkiOiIiLCJzZXgiOiJNYWxlIiwidGVhbSI6Ik93bmVyIEVuZ2FnZW1lbnQiLCJkZXZpc2Vfcm9sZSI6Ik93bmVyX1BvcnRhbF9Vc2VyIiwicGhvbmVfdmVyaWZpZWQiOnRydWUsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJhZGRyZXNzIjoiIiwidXBkYXRlZF9hdCI6IjE3MDczOTk3NTIiLCJmZWF0dXJlcyI6e30sInN0YXR1c19jb2RlIjoxMDAsIm1pbGxpc19sZWZ0X2Zvcl9wYXNzd29yZF9leHBpcnkiOjk0NjkyMjA2NjUxOCwiYWRkcmVzc0pzb24iOnt9fQ%3D%3D","UUID":"ZjMwZmZlNTgtYTlkNi00NDEzLTlmM2UtY2E5MWI1NTU4ZWUw","QID":37182},
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
# GLOBAL LIMITS
# =========================================================
PROP_PARALLEL_LIMIT = 5
DETAIL_PARALLEL_LIMIT = 8
prop_semaphore = asyncio.Semaphore(PROP_PARALLEL_LIMIT)
detail_semaphore = asyncio.Semaphore(DETAIL_PARALLEL_LIMIT)

HTTP: Optional[aiohttp.ClientSession] = None

CACHE: Dict[str, Any] = {}
CONFIRMED: Dict[str, Any] = {}
TG_OFFSET = 0

# =========================================================
# ✅ 3 MIN ULTRA FAST SNAPSHOT MEMORY
# =========================================================
PROPERTY_SNAPSHOT: Dict[str, Dict[str, Any]] = {}
PROPERTY_ROOMS_SNAPSHOT: Dict[str, Any] = {}   # code -> {floors, rooms[]}
SNAPSHOT_LAST_REFRESH = 0


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
# HELPERS
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
# OYO APIS
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

    out = {"name":"","alternate_name":"","plot_number":"","street":"","pincode":"","city":"","country":"","map_link":"","latitude":None,"longitude":None}
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

                cache_set(ck, rooms, 600)
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


def _parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d")
    except Exception:
        return None


# =========================================================
# ✅ FIXED BOOKED ROOMS (OVERLAP + PAGINATION)
# =========================================================
async def fetch_booked_rooms_precise(P: Dict[str, Any], start_date: str, end_date: str) -> Set[str]:
    """
    ✅ Precise booked rooms for date window:
    booking list -> booking details -> room numbers

    ✅ FIXED with your FINAL LOCKED in-house logic:
    - include only bookings where status == "Checked In"
    - active-date condition:
        if not (ci <= target_dt <= co or (ci == tf_date + timedelta(days=1) and target_dt <= co)):
            continue
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

            # ✅ Your fixed in-house logic
            tf_date = datetime.strptime(start_date, "%Y-%m-%d")
            target_dt = tf_date

            booking_ids: List[str] = []
            for b in bookings.values():
                status = (b.get("status") or "").strip()
                if status != "Checked In":
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

                # ✅ FINAL ACTIVE DATE RULE (LOCKED)
                if not (ci <= target_dt <= co or (ci == tf_date + timedelta(days=1) and target_dt <= co)):
                    continue

                bid = str(b.get("booking_no") or "").strip()
                if bid:
                    booking_ids.append(bid)

            # ✅ Fetch precise room numbers using details API
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


async def count_available_rooms(P: Dict[str, Any], from_: str, to: str) -> int:
    """
    ✅ Correct available rooms:
    total rooms - booked rooms (precise overlap)
    """
    ck = f"avail:v2:{P['QID']}:{from_}:{to}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    rooms = await fetch_rooms(P)
    total_rooms = len(rooms)

    booked_rooms = await fetch_booked_rooms_precise(P, from_, to)
    available = max(total_rooms - len(booked_rooms), 0)

    cache_set(ck, available, 120)
    return available


# =========================================================
# ✅ ROOM PRICE LOGIC (highest per-day from last 10 bookings)
# =========================================================
async def compute_room_price_map(P: Dict[str, Any], prop_code: str) -> Dict[str, float]:
    """
    For each room:
    - find last 10 bookings where that room assigned
    - compute per-day price = (paid + balance)/stay_days
    - room_price = max(per-day price in last 10 bookings)
    """
    ck = f"room_prices:{prop_code}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    # fetch last 90 days bookings
    till = datetime.now().date()
    frm = (till - timedelta(days=90)).strftime("%Y-%m-%d")
    till_s = till.strftime("%Y-%m-%d")

    url = "https://www.oyoos.com/hms_ms/api/v1/get_booking_with_ids"
    cookies = {"uif": P["UIF"], "uuid": P["UUID"]}
    headers = {"accept": "application/json", "x-qid": str(P["QID"]), "x-source-client": "merchant"}

    # store recent bookings metadata
    recent_bookings: List[Dict[str, Any]] = []
    offset = 0

    try:
        while True:
            params = {
                "qid": P["QID"],
                "checkin_from": frm,
                "checkin_till": till_s,
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
                ids = data.get("bookingIds") or []
                bookings = (data.get("entities", {}) or {}).get("bookings", {}) or {}

                if not bookings:
                    break

                # keep recent first
                for b in bookings.values():
                    status = str(b.get("status") or "").strip()
                    if status in ("Cancelled", "No Show"):
                        continue
                    recent_bookings.append(b)

                if len(ids) < 100:
                    break
                offset += 100

            # safety limit: avoid too heavy
            if len(recent_bookings) > 800:
                break

        # booking details for room assignment (batch)
        # map room -> list(per_day_price) limited 10
        room_prices: Dict[str, List[float]] = {}

        # take most recent first
        recent_bookings = sorted(recent_bookings, key=lambda x: str(x.get("checkin") or ""), reverse=True)

        for b in recent_bookings:
            if sum(len(v) for v in room_prices.values()) > 400:
                break

            bid = str(b.get("booking_no") or "").strip()
            if not bid:
                continue

            ci = _parse_dt(b.get("checkin"))
            co = _parse_dt(b.get("checkout"))
            if not ci or not co:
                continue

            stay_days = max((co - ci).days, 1)
            paid = float(b.get("get_amount_paid") or 0.0)
            balance = float(b.get("payable_amount") or 0.0)
            total_amt = paid + balance
            per_day = float(total_amt) / float(stay_days)

            assigned_rooms = await fetch_booking_details_rooms(P, bid)
            if not assigned_rooms:
                continue

            for rn in assigned_rooms:
                lst = room_prices.get(rn, [])
                if len(lst) < 10:
                    lst.append(per_day)
                    room_prices[rn] = lst

        # finalize: room -> max(per_day)
        out: Dict[str, float] = {}
        for rn, prices in room_prices.items():
            out[rn] = round(max(prices) if prices else 0.0, 2)

        cache_set(ck, out, 180)  # refresh with snapshot (3 min)
        return out

    except Exception:
        cache_set(ck, {}, 120)
        return {}


# =========================================================
# SNAPSHOT REFRESH LOOP (every 3 minutes)
# =========================================================
async def refresh_all_snapshots_loop():
    global PROPERTY_SNAPSHOT, PROPERTY_ROOMS_SNAPSHOT, SNAPSHOT_LAST_REFRESH
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

                    # booked overlap for today window
                    booked_rooms = await fetch_booked_rooms_precise(P, today, tomorrow)

                    # per-room price map
                    room_price_map = await compute_room_price_map(P, code)

                    floors = sorted({r["floor"] for r in rooms}) or ["1"]
                    out_rooms = []
                    for r in rooms:
                        rn = r["room"]
                        status = "booked" if rn in booked_rooms else "available"
                        std_price = float(room_price_map.get(rn, 0.0) or 0.0)
                        out_rooms.append({**r, "status": status, "standard_price": std_price})

                    # property today price = least room price (min)
                    non_zero_prices = [x["standard_price"] for x in out_rooms if x.get("standard_price", 0) > 0]
                    today_price = min(non_zero_prices) if non_zero_prices else 0.0

                    address = " ".join([
                        d.get("plot_number", ""),
                        d.get("street", ""),
                        d.get("city", ""),
                        d.get("pincode", "")
                    ]).strip()

                    name = d.get("alternate_name") or d.get("name") or code

                    available = max(len(rooms) - len(booked_rooms), 0)

                    PROPERTY_ROOMS_SNAPSHOT[code] = {
                        "floors": floors,
                        "rooms": out_rooms
                    }

                    return code, {
                        "code": code,
                        "name": name,
                        "address": address,
                        "city": d.get("city", ""),
                        "pincode": d.get("pincode", ""),
                        "map_link": d.get("map_link", ""),
                        "latitude": d.get("latitude", None),
                        "longitude": d.get("longitude", None),
                        "today_price": float(round(today_price)),   # ✅ property today price
                        "available_rooms": available,
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

        await asyncio.sleep(180)  # every 3 minutes


# =========================================================
# TELEGRAM POLLING
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
@app.get("/api/health")
async def health():
    return {"ok": True, "time": int(time.time())}


@app.get("/api/search")
async def search(location: str = "", from_: str = "", to: str = ""):
    """
    ✅ Ultra-fast:
    - returns from snapshot (memory)
    - only distance computed dynamically
    """
    loc = (location or "").strip()
    user_geo = await geocode_free(loc) if loc else None

    hotels = list(PROPERTY_SNAPSHOT.values()) if PROPERTY_SNAPSHOT else []

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

    return {"hotels": hotels, "snapshot_time": SNAPSHOT_LAST_REFRESH}


@app.get("/api/property/{code}")
async def property_details(code: str, from_: str = "", to: str = ""):
    P = PROPERTIES.get(code)
    if not P:
        return JSONResponse({"error": "Invalid property"}, status_code=404)

    # return from snapshot (ultra fast)
    prop = PROPERTY_SNAPSHOT.get(code)
    prop_rooms = PROPERTY_ROOMS_SNAPSHOT.get(code)

    if not prop or not prop_rooms:
        # fallback live (rare first few seconds after boot)
        d = await fetch_property_details(P)
        rooms = await fetch_rooms(P)
        floors = sorted({r["floor"] for r in rooms}) or ["1"]
        address = " ".join([
            d.get("plot_number", ""),
            d.get("street", ""),
            d.get("city", ""),
            d.get("pincode", "")
        ]).strip()

        return {
            "code": code,
            "name": d.get("alternate_name") or d.get("name") or code,
            "address": address,
            "map_link": d.get("map_link", ""),
            "latitude": d.get("latitude", None),
            "longitude": d.get("longitude", None),
            "today_price": 0,
            "floors": floors,
            "rooms": [{**r, "status": "available", "standard_price": 0} for r in rooms]
        }

    return {
        "code": prop["code"],
        "name": prop["name"],
        "address": prop["address"],
        "map_link": prop["map_link"],
        "latitude": prop["latitude"],
        "longitude": prop["longitude"],
        "today_price": prop.get("today_price", 0),
        "floors": prop_rooms["floors"],
        "rooms": prop_rooms["rooms"]
    }


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
