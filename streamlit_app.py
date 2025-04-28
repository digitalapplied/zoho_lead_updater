#!/usr/bin/env python3
"""
streamlit_app.py  ·  v3.4 (TypeError Fixes & CSV Removal)
Streamlit UI for Zoho Lead-Status Bulk Updater.
Supports TXT upload, CV fetch, credential override, progress bar, field list.
"""

import logging, textwrap, io, math, json
from datetime import datetime
from pathlib import Path

import pandas as pd # Keep pandas for DataFrame display
import streamlit as st
from dotenv import load_dotenv

# Try importing zoho_bulk, handle potential ImportError
try:
    from zoho_bulk import (
        VALID_STATUSES, bulk_update, fetch_leads_by_cvid, get_module_fields,
        get_access_token, CHUNK_SIZE,
        DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_REFRESH_TOKEN,
        DEFAULT_API_DOMAIN, DEFAULT_ACCOUNTS_URL, MODULE_API_NAME,
        FIELD_TO_UPDATE # Make sure FIELD_TO_UPDATE is defined/imported if used directly
    )
except ImportError as import_err:
    st.error(f"""
        **Fatal Error:** Could not import the `zoho_bulk.py` helper file.

        Please ensure `zoho_bulk.py` exists in the same directory.

        *Details: {import_err}*
        """)
    st.stop()

# ----- page config -----------------------------------------------------------
st.set_page_config(page_title="Zoho Lead Updater", page_icon="🛠️", layout="wide")
load_dotenv()
logging.getLogger("urllib3").setLevel(logging.WARNING) # Suppress noisy logs

# ----- Initialize Session State ---------------------------------------------
default_creds = {
    'client_id': DEFAULT_CLIENT_ID, 'client_secret': DEFAULT_CLIENT_SECRET,
    'refresh_token': DEFAULT_REFRESH_TOKEN, 'api_domain': DEFAULT_API_DOMAIN,
    'accounts_url': DEFAULT_ACCOUNTS_URL
}
for key, default in default_creds.items():
    st.session_state.setdefault(f'cred_{key}', default or "")

st.session_state.setdefault('ids_text_area', "")
st.session_state.setdefault('lead_fields_df', None)
# Remove mixed_status_data state as CSV with status column is no longer supported
if 'mixed_status_data' in st.session_state:
    del st.session_state['mixed_status_data']
st.session_state.setdefault('confirm_pending', False)
st.session_state.setdefault('execute_update', False)

# ----- helpers ---------------------------------------------------------------
def parse_ids(text: str) -> list[str]:
    """Extracts unique, numeric-only IDs from a string block."""
    parsed = []
    ignored_count = 0
    processed_lines = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in processed_lines: continue
        processed_lines.add(stripped)
        if stripped.isdigit():
            parsed.append(stripped)
        elif stripped:
            ignored_count += 1
            logging.warning(f"Ignoring non-numeric line: {stripped!r}")
    if ignored_count > 0:
         st.toast(f"Ignored {ignored_count} non-numeric/blank lines.", icon="⚠️")
    unique_ids = sorted(list(set(parsed)))
    if len(parsed) > len(unique_ids):
        logging.info(f"Removed {len(parsed) - len(unique_ids)} duplicate IDs.")
        st.toast(f"Removed {len(parsed) - len(unique_ids)} duplicate IDs.", icon="ℹ️")
    return unique_ids

def style_summary(ok: int, bad: int):
    color_ok = "#28a745"; color_bad = "#dc3545"
    style = "font-size: 1.2rem; font-weight: bold; margin-bottom: 1rem; padding: 8px; border-radius: 5px;"
    return f"""<div style="{style}"><span style='color:{color_ok};'>✅ {ok} Succeeded</span>  |  <span style='color:{color_bad};'>❌ {bad} Failed</span></div>"""

def get_effective_credentials():
    """Returns credentials dict, prioritizing sidebar inputs over .env defaults."""
    creds = {
        "client_id": st.session_state.cred_client_id or DEFAULT_CLIENT_ID,
        "client_secret": st.session_state.cred_client_secret or DEFAULT_CLIENT_SECRET,
        "refresh_token": st.session_state.cred_refresh_token or DEFAULT_REFRESH_TOKEN,
        "accounts_url": st.session_state.cred_accounts_url or DEFAULT_ACCOUNTS_URL,
        "api_domain": st.session_state.cred_api_domain or DEFAULT_API_DOMAIN
    }
    if not all([creds['client_id'], creds['client_secret'], creds['refresh_token']]):
        st.error("Missing required Zoho Credentials. Check sidebar or `.env`."); return None
    return creds

# ----- sidebar: Settings & Credentials ---------------------------------------
with st.sidebar:
    # logo() # Add back if logo function/file exists
    st.title("⚙️ Settings")
    with st.expander("Zoho API Credentials (Override)", expanded=False):
        st.caption("Leave blank to use `.env` file.")
        st.text_input("Client ID", key="cred_client_id", placeholder="From .env..." if DEFAULT_CLIENT_ID else "Required")
        st.text_input("Client Secret", type="password", key="cred_client_secret", placeholder="Enter to override")
        st.text_input("Refresh Token", type="password", key="cred_refresh_token", placeholder="Enter to override")
        st.text_input("API Domain", key="cred_api_domain", help="e.g., https://www.zohoapis.eu")
        st.text_input("Accounts URL", key="cred_accounts_url", help="e.g., https://accounts.zoho.eu/oauth/v2/token")

    st.divider()
    st.header("🎯 1. Select Target Status")
    target_status_default = st.selectbox("Default Lead Status:", VALID_STATUSES,
        index=VALID_STATUSES.index("Junk Lead") if "Junk Lead" in VALID_STATUSES else 0,
        key='target_status_selectbox'
    )

    st.divider()
    st.header("📋 2. Load Lead IDs")
    upload_col, fetch_col = st.columns(2)
    with upload_col:
        # Simplified: Only TXT upload relevant now
        uploaded_file = st.file_uploader("Upload TXT File", type=["txt"], help="File with one numeric Zoho Lead ID per line.")
    with fetch_col:
        cvid_input = st.text_input("Custom View ID", placeholder="e.g., 164...", help="Numeric ID from Zoho URL.")
        fetch_all_pages = st.checkbox("Fetch all pages", value=True, help="Get >200 records.")
        fetch_btn = st.button("Fetch IDs from CV", disabled=not cvid_input.strip().isdigit())

    # --- ID Loading Logic (Simplified - No CSV Check) ---
    if uploaded_file:
        try:
            content_str = uploaded_file.read().decode("utf-8")
            st.session_state['ids_text_area'] = content_str # Load content into text area
            st.success(f"Loaded IDs from '{uploaded_file.name}'. Review/edit below.")
        except Exception as e: st.error(f"File read error: {e}"); logging.exception("File upload error")

    if fetch_btn:
        if cvid_input and cvid_input.strip().isdigit():
            try:
                effective_creds = get_effective_credentials();
                if not effective_creds: st.stop()
                with st.spinner(f"Fetching CV {cvid_input}..."):
                    # FIX 2: Explicitly pass only needed args to get_access_token
                    token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                    try:
                        token = get_access_token(**token_creds)
                    except Exception as auth_err:
                        st.error(f"❌ Zoho Auth Failed: {auth_err}. Check creds & region URLs."); logging.error(f"Token fetch failed: {auth_err}"); st.stop()

                    leads = fetch_leads_by_cvid(token, cvid_input.strip(), api_domain=effective_creds['api_domain'], fetch_all=fetch_all_pages)
                if leads:
                    ids = [str(l['id']) for l in leads if str(l.get('id', '')).isdigit()]
                    st.session_state['ids_text_area'] = "\n".join(sorted(list(set(ids))));
                    st.success(f"Fetched {len(ids)} IDs."); st.rerun()
                else: st.warning("No leads found.")
            except Exception as e: st.error(f"Fetch error: {e}"); logging.exception("CV fetch failed")
        else: st.error("Invalid CV ID.")

# ----- main Area: Review & Execute ------------------------------------------
st.header("📄 3. Review IDs & Execute")

ids_text_display = st.text_area(
    "Lead IDs to Update (one per line):", value=st.session_state.get('ids_text_area', ""),
    height=300, placeholder="Paste IDs, or load from sidebar...",
    key='ids_text_area_widget_main', help="Review/edit IDs. Blank/non-numeric lines ignored."
)
if ids_text_display != st.session_state.get('ids_text_area', ""): # Detect manual edits
    st.session_state['ids_text_area'] = ids_text_display
    st.rerun() # Rerun to update counts

ids_final = parse_ids(st.session_state['ids_text_area'])
rows_to_process = [{"id": i, "status": target_status_default} for i in ids_final]
processing_mode_message = f"{len(ids_final)} IDs from text area (target: '{target_status_default}')"

col1_main, col2_main = st.columns([3, 1])
with col1_main:
    st.caption(f"Ready to process: **{processing_mode_message}**")
with col2_main:
    run_update_btn = st.button(f"🚀 Update {len(rows_to_process)} Records",
        disabled=not rows_to_process, type="primary", use_container_width=True, key="run_update_main_btn")

# Confirmation Flow
if run_update_btn:
    if rows_to_process: st.session_state['confirm_pending'] = True; st.rerun()
    else: st.warning("No valid IDs entered.")

if st.session_state.get('confirm_pending', False):
    st.warning(f"Confirm update for **{len(rows_to_process)}** records to '{target_status_default}'. Irreversible.", icon="⚠️")
    confirm_col1, confirm_col2, _ = st.columns([1, 1, 3])
    if confirm_col1.button("Confirm & Proceed", type="primary", key="confirm_yes"):
        st.session_state['confirm_pending'] = False; st.session_state['execute_update'] = True; st.rerun()
    if confirm_col2.button("Cancel", key="confirm_no"):
        st.session_state['confirm_pending'] = False; st.info("Update cancelled."); st.rerun()

# ----- Execution Block -------------------------------------------------------
if st.session_state.get('execute_update', False):
    st.session_state['execute_update'] = False # Reset

    st.header("📊 Update Results")
    st.info(f"Processing {len(rows_to_process)} records...")
    prog_container = st.empty(); prog_container.progress(0, text="Initiating...")
    start_time = datetime.now()

    progress_state = {'processed_chunks': 0}
    total_chunks = math.ceil(len(rows_to_process) / CHUNK_SIZE) or 1
    def progress_hook(chunk_num):
         progress_state['processed_chunks'] = chunk_num
         progress = min(1.0, progress_state['processed_chunks'] / total_chunks)
         prog_container.progress(progress, text=f"Processing chunk {progress_state['processed_chunks']}/{total_chunks}...")

    try:
        effective_creds = get_effective_credentials();
        if not effective_creds: st.stop()
        results = bulk_update(rows_to_process, progress_hook=progress_hook, **effective_creds)
        prog_container.progress(1.0, text="Update process complete!")
    except Exception as exc:
        st.error(f"Critical Failure: {exc}"); logging.exception("Bulk update failed"); prog_container.empty(); st.stop()

    end_time = datetime.now(); duration = end_time - start_time
    st.caption(f"Total processing time: {duration}")

    # Results Processing (Robust version from v3.3)
    if results and isinstance(results, list):
        processed_results = []
        for item in results:
            if isinstance(item, dict):
                processed_item = {"id": item.get('id', 'UNKNOWN'), "status": item.get('status', 'error'),
                                  "code": item.get('code', 'MISSING_CODE'), "message": item.get('message', 'No message'),
                                  "details": item.get('details', {})}
                if processed_item['id'] == 'UNKNOWN' and isinstance(processed_item['details'], dict):
                    processed_item['id'] = str(processed_item['details'].get('id', 'UNKNOWN'))
                processed_results.append(processed_item)
            else:
                 logging.error(f"Bad item type in results: {type(item)} - {item}")
                 processed_results.append({"id": "INVALID_ITEM", "status": "error", "code": "INVALID_RESULT",
                                           "message": "Bad item format.", "details": {"item": str(item)[:100]}})
        df = pd.DataFrame(processed_results)
        required_cols = ["id", "status", "code", "message", "details"]; display_cols = []
        for col in required_cols:
            if col not in df.columns: df[col] = None
            display_cols.append(col) # Add even if initially missing

        df_display = df[display_cols].copy()
        df_display['details'] = df_display['details'].apply(lambda x: json.dumps(x) if isinstance(x, dict) else str(x))

        ok_df = df[df["status"] == "success"]; bad_df = df[df["status"] != "success"]
        ok_count, bad_count = len(ok_df), len(bad_df)
        st.markdown(style_summary(ok_count, bad_count), unsafe_allow_html=True)
        st.dataframe(df_display, use_container_width=True, height=300)

        if not bad_df.empty:
            try:
                csv_fail = bad_df.to_csv(index=False).encode('utf-8')
                ts_fail  = datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")
                st.download_button(f"Download {bad_count} failed", csv_fail, f"failed_{ts_fail}.csv", "text/csv", key="dl_fail")
            except Exception as e: st.error(f"CSV download prep failed: {e}")
        elif ok_count > 0: st.success("All submitted records processed successfully!")
        else: st.warning("No records succeeded.")
    else: st.warning("No results returned.")

st.divider()
# ----- Fetch Fields Section --------------------------------------------------
st.header("📚 View Lead Field Names (Optional)")
if st.button("Show Available Lead Fields", key="fetch_fields"):
     if st.session_state.get('lead_fields_df') is not None:
          st.caption("Using cached field data.")
          st.dataframe(st.session_state['lead_fields_df'], use_container_width=True, height=500)
          st.download_button("Download Fields", st.session_state['lead_fields_df'].to_csv(index=False).encode('utf-8'),
                           f"{MODULE_API_NAME}_fields.csv", "text/csv", key="dl_fields_cached")
     else:
        try:
            effective_creds = get_effective_credentials();
            if not effective_creds: st.stop()
            with st.spinner(f"Fetching fields..."):
                # FIX 1: Call get_module_fields correctly (remove module=...)
                token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                token = get_access_token(**token_creds)
                fields = get_module_fields(token, api_domain=effective_creds['api_domain']) # Removed module= arg

            if fields:
                df_fields = pd.DataFrame(fields)[['api_name', 'field_label', 'data_type']].sort_values('field_label')
                st.session_state['lead_fields_df'] = df_fields # Cache
                st.dataframe(df_fields, use_container_width=True, height=500)
                st.download_button("Download Fields", df_fields.to_csv(index=False).encode('utf-8'),
                           f"{MODULE_API_NAME}_fields.csv", "text/csv", key="dl_fields_new")
            else: st.warning("No field data returned."); st.session_state['lead_fields_df'] = pd.DataFrame()
        except Exception as e: st.error(f"Fetch fields error: {e}"); logging.exception("Field fetch error")

# ----- Footer ----------------------------------------------------------------
st.divider()
with st.expander("ℹ️  Help & About"):
    st.markdown(textwrap.dedent(f"""
        **Zoho CRM Lead Status Bulk Updater v3.4**
        Updates '{FIELD_TO_UPDATE}' for '{MODULE_API_NAME}' records.

        **Usage:**
        1. Creds: Use `.env` or sidebar override.
        2. Status: Select default status (sidebar).
        3. Load IDs: Upload (`.txt`), Fetch (CV ID), or Paste.
        4. Review: Check/edit IDs in main text area.
        5. Execute: Click Update → Confirm.
        6. Results: View summary/table. Download failures.
        7. Fields: View/download field names.

        *v3.4 removes mixed-status CSV upload.*
        """))