#!/usr/bin/env python3
"""
zoho_bulk.py  ·  v3.2
All Zoho-API interaction (token refresh, CV fetch, field list, bulk update).
"""

import json, logging, math, os, re, time
from typing import List, Dict, Iterable, Optional

import requests
from dotenv import load_dotenv

# ─────────────────────────────────── config ──────────────────────────────────
load_dotenv()

DEFAULT_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
DEFAULT_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
DEFAULT_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")

DEFAULT_API_DOMAIN    = os.getenv("ZOHO_API_DOMAIN",   "https://www.zohoapis.com")
DEFAULT_ACCOUNTS_URL  = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com/oauth/v2/token")

MODULE_API_NAME = "Leads"
FIELD_TO_UPDATE = "Lead_Status"

PER_PAGE   = 200     # fetch
CHUNK_SIZE = 100     # update
MAX_RETRY  = 3
BACKOFF    = 2
TIMEOUT    = 60

VALID_STATUSES = [
    "Not Contacted", "Self Storage Questions Sent", "Move Questionnaire Sent",
    "Move Questionnaire Follow Up", "Move Questionnaire Completed",
    "Onsite Survey Booked", "On Hold", "Duplicate Lead", "Closed Lost",
    "Junk Lead", "Not Qualified",
]

# ──────────────────────────── logger (scrubs secrets) ────────────────────────
_scrub = re.compile("|".join(
    re.escape(s) for s in (DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_REFRESH_TOKEN) if s
))
class _Redact(logging.Filter):
    def filter(self, record):
        record.msg = _scrub.sub("*****", str(record.msg))
        return True

log = logging.getLogger(__name__)
if not log.hasHandlers():
    fh = logging.FileHandler("zoho_bulk.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    fh.addFilter(_Redact())
    log.addHandler(fh)
    log.setLevel(logging.INFO)

# ───────────────────────── utility helpers ───────────────────────────────────
def _chunks(seq: Iterable, n: int):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def _request(method: str, url: str, token: str, **kw):
    kw.setdefault("timeout", TIMEOUT)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    last = None
    for attempt in range(1, MAX_RETRY+1):
        resp = requests.request(method, url, headers=headers, **kw)
        if resp.status_code in (429, 500, 502, 503, 504):
            last = resp
            time.sleep(BACKOFF * 2**(attempt-1)); continue
        resp.raise_for_status()
        return resp
    raise requests.HTTPError(last)

# ───────────────────────────── auth ──────────────────────────────────────────
def get_access_token(client_id=None, client_secret=None, refresh_token=None,
                     accounts_url=None) -> str:
    cid  = client_id     or DEFAULT_CLIENT_ID
    csec = client_secret or DEFAULT_CLIENT_SECRET
    rtok = refresh_token or DEFAULT_REFRESH_TOKEN
    url  = accounts_url  or DEFAULT_ACCOUNTS_URL
    if not all((cid, csec, rtok)):
        raise ValueError("Zoho creds missing (check .env or sidebar).")
    r = requests.post(url, data={
        "refresh_token": rtok, "client_id": cid,
        "client_secret": csec, "grant_type": "refresh_token"},
        timeout=TIMEOUT)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"Refresh failed: {r.text}")
    return tok

# ──────────────────────── CV fetch & fields ──────────────────────────────────
def fetch_leads_by_cvid(token: str, cvid: str, *,
                        api_domain=DEFAULT_API_DOMAIN, fetch_all=False) -> List[Dict]:
    url = f"{api_domain}/crm/v8/{MODULE_API_NAME}"
    out, page = [], 1
    while True:
        p = {"cvid": cvid, "per_page": PER_PAGE, "page": page}
        data = _request("GET", url, token, params=p).json().get("data", [])
        out.extend(data)
        if not fetch_all or len(data) < PER_PAGE: break
        page += 1
    return out

def get_module_fields(token: str, *, api_domain=DEFAULT_API_DOMAIN) -> List[Dict]:
    u = f"{api_domain}/crm/v8/settings/fields"
    return _request("GET", u, token, params={"module": MODULE_API_NAME}).json().get("fields", [])

# ─────────────────────────── bulk update ─────────────────────────────────────
def _update_chunk(token: str, payload: List[Dict], *, api_domain: str) -> List[Dict]:
    url = f"{api_domain}/crm/v8/{MODULE_API_NAME}"
    ids_sent = [p["id"] for p in payload]
    res = _request("PUT", url, token, json={"data": payload})
    items = res.json().get("data", [])
    # —— diagnostic: any ID missing in response? ——
    got = {str(i.get("details", {}).get("id", i.get("id"))) for i in items}
    missing = [i for i in ids_sent if str(i) not in got]
    for mid in missing:
        chk_url = f"{api_domain}/crm/v8/{MODULE_API_NAME}/{mid}"
        try:
            chk = _request("GET", chk_url, token)
            code = "PERMISSION_DENIED" if chk.status_code == 403 else "UNKNOWN_SKIP"
        except requests.HTTPError as e:
            code = "NOT_FOUND" if e.response.status_code == 404 else "UNKNOWN_SKIP"
        items.append({"id": mid, "status": "error", "code": code,
                      "message": "Zoho did not return a result for this ID",
                      "details": {}})
    return items

def bulk_update(rows: List[Dict], *, progress_hook=None, **cred) -> List[Dict]:
    bad = {r["status"] for r in rows if r["status"] not in VALID_STATUSES}
    if bad: raise ValueError(f"Invalid status: {', '.join(bad)}")

    token = get_access_token(**{k: cred.get(k) for k in
                                ("client_id","client_secret","refresh_token","accounts_url")})
    api_domain = cred.get("api_domain", DEFAULT_API_DOMAIN)

    out, chunks = [], math.ceil(len(rows)/CHUNK_SIZE) or 1
    for idx, chunk in enumerate(_chunks(rows, CHUNK_SIZE), 1):
        payload = [{"id": r["id"], FIELD_TO_UPDATE: r["status"]} for r in chunk]
        out.extend(_update_chunk(token, payload, api_domain=api_domain))
        if progress_hook: progress_hook(idx)
    return out
