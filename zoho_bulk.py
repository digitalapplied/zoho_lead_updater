#!/usr/bin/env python3
"""
zoho_bulk.py  ·  v3.4 (Fix ID Fetching Chunking)
All Zoho-API interaction (token refresh, CV fetch, field list, bulk update).
Adds fetching specific fields for records, handles ID list chunking.
"""

import json, logging, math, os, re, time
from typing import List, Dict, Iterable, Optional, Union

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

PER_PAGE         = 200  # fetch (max for CV listing)
IDS_PER_REQUEST  = 100  # fetch (max for GET by IDs param) - ADJUST IF NEEDED based on API limits
CHUNK_SIZE       = 100  # update (max for bulk update/insert)
MAX_RETRY        = 3
BACKOFF          = 2
TIMEOUT          = 60

VALID_STATUSES = [
    "Not Contacted", "Self Storage Questions Sent", "Move Questionnaire Sent",
    "Move Questionnaire Follow Up", "Move Questionnaire Completed",
    "Onsite Survey Booked", "On Hold", "Duplicate Lead", "Closed Lost",
    "Junk Lead", "Not Qualified",
]

# ──────────────────────────── logger (scrubs secrets) ────────────────────────
# (Logger setup remains the same)
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
    # (This is used only for *bulk_update* now, not fetch_records)
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def _request(method: str, url: str, token: str, **kw):
    # (Remains the same as v3.3 - error handling improved)
    kw.setdefault("timeout", TIMEOUT)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    last = None
    for attempt in range(1, MAX_RETRY+1):
        try:
            resp = requests.request(method, url, headers=headers, **kw)
            log.debug(f"Request: {method} {url} Params: {kw.get('params')} Data: {kw.get('json')}")
            log.debug(f"Response: {resp.status_code} Body: {resp.text[:500]}") # Log snippet of response

            # --- Specific Status Code Handling ---
            if resp.status_code == 204: # No Content is often a valid success response
                log.info(f"Received 204 No Content for {method} {url}. Returning empty list/dict.")
                return resp # Allow calling function to handle 204

            if resp.status_code in (429, 500, 502, 503, 504): # Retryable server errors/rate limits
                last = resp
                sleep_time = BACKOFF * 2**(attempt-1)
                log.warning(f"Received {resp.status_code}. Retrying in {sleep_time}s... (Attempt {attempt}/{MAX_RETRY})")
                time.sleep(sleep_time)
                continue

            resp.raise_for_status() # Raise HTTPError for other 4xx/5xx errors
            return resp

        except requests.exceptions.RequestException as e:
            log.error(f"Request failed for {method} {url}: {e}")
            last = getattr(e, 'response', None) # Store response if available in exception
            if attempt == MAX_RETRY:
                raise # Re-raise the exception after the last attempt
            sleep_time = BACKOFF * 2**(attempt-1)
            log.warning(f"Request Exception. Retrying in {sleep_time}s... (Attempt {attempt}/{MAX_RETRY})")
            time.sleep(sleep_time)

    # If loop finishes without returning (all retries failed), raise the last error
    if last:
        raise requests.HTTPError(f"Request failed after {MAX_RETRY} attempts. Last status: {last.status_code}", response=last)
    else:
        # Should not happen if requests.exceptions.RequestException was caught, but as a fallback
        raise requests.HTTPError(f"Request failed after {MAX_RETRY} attempts with no response object.")

# ───────────────────────────── auth ──────────────────────────────────────────
def get_access_token(client_id=None, client_secret=None, refresh_token=None,
                     accounts_url=None) -> str:
    # (Remains the same)
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

# ──────────────────────── fetch records & fields ───────────────────────────
def fetch_records(token: str, *,
                  module=MODULE_API_NAME,
                  cvid: Optional[str] = None,
                  ids: Optional[List[str]] = None,
                  fields: Optional[List[str]] = None,
                  api_domain=DEFAULT_API_DOMAIN,
                  fetch_all=False) -> List[Dict]:
    """
    Fetches records based on Custom View ID or a list of specific Record IDs.
    Can specify which fields to retrieve. Handles pagination for CV and chunking for IDs.

    Args:
        token: Valid Zoho API access token.
        module: API name of the module (default: MODULE_API_NAME).
        cvid: ID of the Custom View to fetch records from.
        ids: List of specific record IDs to fetch. Will be chunked automatically.
        fields: List of API names of the fields to retrieve. If None, fetches default fields.
                'id' is always included if specific fields are requested.
        api_domain: Zoho API domain (e.g., https://www.zohoapis.com).
        fetch_all: If True and using cvid, fetches all pages (up to API limits). Ignored if using ids.

    Returns:
        List of dictionaries, where each dictionary represents a record.

    Raises:
        ValueError: If both cvid and ids are provided, or neither is provided.
        requests.HTTPError: If the API request fails after retries.
    """
    if cvid and ids:
        raise ValueError("Provide either 'cvid' or 'ids', not both.")
    if not cvid and not ids:
        raise ValueError("Provide either 'cvid' or 'ids' to fetch records.")

    base_url = f"{api_domain}/crm/v8/{module}"
    all_records = []

    # Prepare common parameters
    common_params = {}
    if fields:
        unique_fields = set(f.strip() for f in fields if f.strip()) # Clean field names
        unique_fields.add('id') # Ensure 'id' is always fetched
        common_params["fields"] = ",".join(sorted(list(unique_fields)))
        log.info(f"Requesting specific fields: {common_params['fields']}")
    else:
        log.info("Requesting default fields.")

    if cvid:
        # Fetching by Custom View (handles pagination)
        page = 1
        while True:
            params = {"cvid": cvid, "per_page": PER_PAGE, "page": page, **common_params}
            log.info(f"Fetching page {page} for CV ID {cvid}")
            resp = _request("GET", base_url, token, params=params)
            if resp.status_code == 204:
                log.info(f"Received 204 No Content for page {page}. End of CV records.")
                break
            try:
                resp_json = resp.json()
                data = resp_json.get("data", [])
            except json.JSONDecodeError:
                log.error(f"Failed to decode JSON from CV response: {resp.text}")
                raise requests.HTTPError(f"Failed to decode JSON CV response. Status: {resp.status_code}", response=resp)

            if not data:
                log.info(f"No more data found on page {page}.")
                break

            all_records.extend(data)
            log.info(f"Fetched {len(data)} records on page {page}. Total fetched: {len(all_records)}")

            # Check pagination info if available, otherwise rely on fetch_all and per_page count
            info = resp_json.get("info", {})
            more_records = info.get("more_records", False) if info else (len(data) == PER_PAGE)

            if fetch_all and more_records:
                page += 1
                time.sleep(0.5) # Rate limiting
            else:
                break
    elif ids:
        # Fetching by specific IDs (handles chunking)
        total_ids_to_fetch = len(ids)
        log.info(f"Fetching {total_ids_to_fetch} records by ID in chunks of {IDS_PER_REQUEST}.")
        for i, id_chunk in enumerate(_chunks(ids, IDS_PER_REQUEST)): # Use internal chunking helper
            params = {"ids": ",".join(id_chunk), **common_params}
            log.info(f"Fetching chunk {i+1}/{math.ceil(total_ids_to_fetch/IDS_PER_REQUEST)} ({len(id_chunk)} IDs)")
            resp = _request("GET", base_url, token, params=params)
            if resp.status_code == 204:
                log.warning(f"Received 204 No Content for ID chunk {i+1}. IDs: {id_chunk}")
                continue # Skip to next chunk
            try:
                data = resp.json().get("data", [])
                if data:
                     all_records.extend(data)
                     log.info(f"Fetched {len(data)} records in chunk {i+1}. Total fetched: {len(all_records)}")
                else:
                     log.warning(f"No data returned for ID chunk {i+1}. IDs: {id_chunk}")

            except json.JSONDecodeError:
                 log.error(f"Failed to decode JSON from ID fetch response: {resp.text}")
                 # Consider how to handle partial failures - maybe add placeholders? For now, raise.
                 raise requests.HTTPError(f"Failed to decode JSON ID fetch response. Status: {resp.status_code}", response=resp)

            # Optional delay between chunks if hitting rate limits
            if i + 1 < math.ceil(total_ids_to_fetch / IDS_PER_REQUEST):
                time.sleep(0.5)

    log.info(f"Finished fetching. Total records retrieved: {len(all_records)}")
    return all_records


def get_module_fields(token: str, module=MODULE_API_NAME, *, api_domain=DEFAULT_API_DOMAIN) -> List[Dict]:
    # (Remains the same as v3.3)
    u = f"{api_domain}/crm/v8/settings/fields"
    params = {"module": module} # Use the provided module name
    log.info(f"Fetching fields for module: {module}")
    resp = _request("GET", u, token, params=params)
    if resp.status_code == 204:
        log.warning(f"No fields returned (204 No Content) for module {module}.")
        return []
    try:
        fields = resp.json().get("fields", [])
        log.info(f"Successfully fetched {len(fields)} fields for module {module}.")
        return fields
    except json.JSONDecodeError:
        log.error(f"Failed to decode JSON fields response for module {module}: {resp.text}")
        raise requests.HTTPError(f"Failed to decode JSON fields response. Status: {resp.status_code}", response=resp)

# ─────────────────────────── bulk update ─────────────────────────────────────
def _update_chunk(token: str, payload: List[Dict], *, module=MODULE_API_NAME, api_domain: str) -> List[Dict]:
    # (Remains the same as v3.3)
    url = f"{api_domain}/crm/v8/{module}" # Use the provided module name
    ids_sent = [p["id"] for p in payload]
    log.info(f"Updating chunk of {len(payload)} records for module {module}. IDs: {ids_sent}")
    res = _request("PUT", url, token, json={"data": payload})

    if res.status_code == 204: # Handle No Content for update operations if applicable
        log.warning(f"Received 204 No Content for PUT {url}. Assuming no results returned.")
        # Construct error items for all sent IDs as Zoho didn't confirm them
        items = [{"id": i, "status": "error", "code": "NO_CONTENT",
                 "message": "Zoho returned 204 No Content, status unknown.", "details": {}} for i in ids_sent]
        return items

    try:
        items = res.json().get("data", [])
    except json.JSONDecodeError:
        log.error(f"Failed to decode JSON from update response: {res.text}")
        raise requests.HTTPError(f"Failed to decode JSON update response. Status: {res.status_code}", response=res)

    # —— diagnostic: any ID missing in response? ——
    got = {str(i.get("details", {}).get("id", i.get("id", "UNKNOWN_ID_IN_RESPONSE"))).strip() for i in items}
    missing = [i for i in ids_sent if str(i).strip() not in got]

    if missing:
        log.warning(f"Missing IDs in response for chunk: {missing}. Querying status individually.")
        for mid in missing:
            chk_url = f"{api_domain}/crm/v8/{module}/{mid}" # Use correct module
            try:
                chk_resp = _request("GET", chk_url, token, params={"fields": "id"}) # Fetch minimal data
                if chk_resp.status_code == 200:
                     code = "POSSIBLY_UPDATED_BUT_MISSING_IN_RESPONSE"
                     message = "Record found, may have updated but wasn't in bulk response."
                     log.info(f"Checked missing ID {mid}: Found.")
                elif chk_resp.status_code == 204:
                    code = "NOT_FOUND_ON_CHECK"
                    message = "Record not found when checking status after missing bulk response."
                    log.warning(f"Checked missing ID {mid}: Not Found (204).")
                else:
                    code = f"CHECK_FAILED_STATUS_{chk_resp.status_code}"
                    message = f"Failed to check status for missing ID. Status: {chk_resp.status_code}"
                    log.error(f"Checked missing ID {mid}: Failed with status {chk_resp.status_code}.")

            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response else None
                if status_code == 404:
                    code = "NOT_FOUND_ON_CHECK"
                    message = "Record not found when checking status after missing bulk response."
                    log.warning(f"Checked missing ID {mid}: Not Found (404).")
                elif status_code == 403:
                     code = "PERMISSION_DENIED_ON_CHECK"
                     message = "Permission denied when checking status for missing ID."
                     log.warning(f"Checked missing ID {mid}: Permission Denied (403).")
                else:
                     code = f"CHECK_FAILED_HTTPERROR_{status_code or 'Unknown'}"
                     message = f"Failed to check status for missing ID due to HTTPError: {e}"
                     log.error(f"Checked missing ID {mid}: HTTPError {e}.")

            except Exception as e:
                 code = "CHECK_FAILED_UNKNOWN_ERROR"
                 message = f"Failed to check status for missing ID due to an unexpected error: {e}"
                 log.error(f"Checked missing ID {mid}: Unknown error {e}.")

            items.append({"id": mid, "status": "error", "code": code, "message": message, "details": {}})

    log.info(f"Finished processing update chunk. Results count: {len(items)}")
    return items


def bulk_update(rows: List[Dict], *, progress_hook=None, module=MODULE_API_NAME, **cred) -> List[Dict]:
    # (Remains the same as v3.3)
    valid_statuses_set = set(VALID_STATUSES)
    bad = {r["status"] for r in rows if r.get("status") and r["status"] not in valid_statuses_set}
    if bad: raise ValueError(f"Invalid status found: {', '.join(bad)}")

    token = get_access_token(**{k: cred.get(k) for k in
                                ("client_id","client_secret","refresh_token","accounts_url")})
    api_domain = cred.get("api_domain", DEFAULT_API_DOMAIN)

    out, total_rows = [], len(rows)
    num_chunks = math.ceil(total_rows / CHUNK_SIZE) or 1
    log.info(f"Starting bulk update for {total_rows} records in {num_chunks} chunks.")

    processed_count = 0
    for idx, chunk in enumerate(_chunks(rows, CHUNK_SIZE), 1):
        payload = [{"id": str(r["id"]), FIELD_TO_UPDATE: r["status"]} for r in chunk if str(r.get("id", "")).isdigit() and r.get("status")]

        if not payload:
             log.warning(f"Chunk {idx}/{num_chunks} is empty after filtering. Skipping.")
             continue

        try:
            chunk_results = _update_chunk(token, payload, module=module, api_domain=api_domain)
            out.extend(chunk_results)
            processed_count += len(chunk)
            log.info(f"Processed chunk {idx}/{num_chunks}. Cumulative records processed: {processed_count}/{total_rows}")
            if progress_hook: progress_hook(idx)
            time.sleep(0.5) # Add delay between chunks
        except requests.HTTPError as e:
            log.error(f"HTTPError processing chunk {idx}: {e}. Response: {e.response.text if e.response else 'No Response'}")
            for r in chunk:
                 out.append({"id": r.get("id", "UNKNOWN_IN_FAILED_CHUNK"), "status": "error",
                            "code": f"CHUNK_FAILED_HTTP_{e.response.status_code if e.response else 'NETWORK_ERROR'}",
                            "message": f"Chunk failed: {e}", "details": {}})
            if progress_hook: progress_hook(idx)
        except Exception as e:
             log.exception(f"Unexpected error processing chunk {idx}: {e}")
             for r in chunk:
                 out.append({"id": r.get("id", "UNKNOWN_IN_FAILED_CHUNK"), "status": "error",
                            "code": "CHUNK_FAILED_UNKNOWN",
                            "message": f"Chunk failed unexpectedly: {e}", "details": {}})
             if progress_hook: progress_hook(idx)

    log.info(f"Bulk update process finished. Returning {len(out)} results.")
    return out