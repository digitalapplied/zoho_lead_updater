#!/usr/bin/env python3
"""
streamlit_app.py  ·  v3.10 (Remove Uploader State Modification)
Streamlit UI for Zoho Lead-Status Bulk Updater & Data Viewer.
Removes the attempt to programmatically clear the file uploader state,
relying on Streamlit's default behavior.
"""

import logging, textwrap, io, math, json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Try importing zoho_bulk, handle potential ImportError
try:
    from zoho_bulk import (
        VALID_STATUSES, bulk_update, fetch_records, get_module_fields,
        get_access_token, CHUNK_SIZE, PER_PAGE, IDS_PER_REQUEST,
        DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_REFRESH_TOKEN,
        DEFAULT_API_DOMAIN, DEFAULT_ACCOUNTS_URL, MODULE_API_NAME,
        FIELD_TO_UPDATE
    )
except ImportError as import_err:
    st.error(f"""
        **Fatal Error:** Could not import the `zoho_bulk.py` helper file.

        Please ensure `zoho_bulk.py` exists in the same directory.

        *Details: {import_err}*
        """)
    st.stop()

# ----- page config -----------------------------------------------------------
st.set_page_config(page_title="Zoho Lead Utility", page_icon="🛠️", layout="wide")
load_dotenv()
logging.getLogger("urllib3").setLevel(logging.WARNING) # Suppress noisy logs
logging.getLogger("requests").setLevel(logging.WARNING)


# ----- HELPER FUNCTIONS -------------------------------------------
# (Helper functions parse_ids, style_summary, get_effective_credentials, sync_ids_from_text_area remain the same as v3.8)
def parse_ids(text: str) -> list[str]:
    """Extracts unique, numeric-only IDs from a string block."""
    parsed = []
    ignored_count = 0
    processed_lines = set()
    if not isinstance(text, str): # Add type check for safety
        logging.warning(f"parse_ids received non-string input: {type(text)}")
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped: continue
        if stripped in processed_lines: continue
        processed_lines.add(stripped)
        if stripped.isdigit():
            parsed.append(stripped)
        else:
            ignored_count += 1
            logging.warning(f"Ignoring non-numeric line: {stripped!r}")
    if ignored_count > 0:
         st.toast(f"Ignored {ignored_count} non-numeric lines.", icon="⚠️")
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

def sync_ids_from_text_area():
    st.session_state.loaded_lead_ids = parse_ids(st.session_state.ids_text_area_content)
    st.session_state.lead_data_df = None
    logging.debug("Synced loaded_lead_ids from text area via callback.")

# ----- Initialize Session State ---------------------------------------------
# (Initialization remains the same as v3.8)
default_creds = {
    'client_id': DEFAULT_CLIENT_ID, 'client_secret': DEFAULT_CLIENT_SECRET,
    'refresh_token': DEFAULT_REFRESH_TOKEN, 'api_domain': DEFAULT_API_DOMAIN,
    'accounts_url': DEFAULT_ACCOUNTS_URL
}
for key, default in default_creds.items():
    st.session_state.setdefault(f'cred_{key}', default or "")

st.session_state.setdefault('ids_text_area_content', "")
st.session_state.setdefault('lead_fields_df', None)
st.session_state.setdefault('field_label_map', {})
st.session_state.setdefault('selected_field_labels', [])
if 'loaded_lead_ids' not in st.session_state:
     st.session_state.loaded_lead_ids = parse_ids(st.session_state.ids_text_area_content)
st.session_state.setdefault('lead_data_df', None)

if 'mixed_status_data' in st.session_state: del st.session_state['mixed_status_data']
if 'ids_text_area' in st.session_state: del st.session_state['ids_text_area']
if 'ids_text_area_widget_main' in st.session_state: del st.session_state['ids_text_area_widget_main']

st.session_state.setdefault('confirm_pending', False)
st.session_state.setdefault('execute_update', False)
st.session_state.setdefault('active_tab', 'Update Status')

# ----- sidebar: Settings & Credentials ---------------------------------------
with st.sidebar:
    st.title("⚙️ Settings & Input")

    # --- Credentials Expander ---
    with st.expander("Zoho API Credentials (Override)", expanded=False):
        # (No changes needed here)
        st.caption("Leave blank to use `.env` file.")
        st.text_input("Client ID", key="cred_client_id", placeholder="From .env..." if DEFAULT_CLIENT_ID else "Required")
        st.text_input("Client Secret", type="password", key="cred_client_secret", placeholder="Enter to override")
        st.text_input("Refresh Token", type="password", key="cred_refresh_token", placeholder="Enter to override")
        st.text_input("API Domain", key="cred_api_domain", help="e.g., https://www.zohoapis.eu")
        st.text_input("Accounts URL", key="cred_accounts_url", help="e.g., https://accounts.zoho.eu/oauth/v2/token")

    st.divider()

    # --- Lead ID Loading ---
    st.header("📋 1. Load Lead IDs")
    st.caption("Paste IDs into the main area below or use the Fetch option.") # Updated caption

    # --- Fetch from Custom View --- # Moved out of column
    cvid_input = st.text_input("Custom View ID", placeholder="e.g., 164...", help="Numeric ID from Zoho URL.", key="cvid_input")
    fetch_all_pages = st.checkbox("Fetch all pages", value=True, help="Get >200 records.", key="cv_fetch_all")
    fetch_cv_btn = st.button("Fetch IDs from CV", disabled=not cvid_input.strip().isdigit(), key="fetch_cv_button")

    # --- Status Selection ---
    st.divider()
    st.header("🎯 Status (for Update Tab)")
    target_status_default = st.selectbox("Target Lead Status:", VALID_STATUSES,
        index=VALID_STATUSES.index("Junk Lead") if "Junk Lead" in VALID_STATUSES else 0,
        key='target_status_selectbox',
        help="Select the status to apply in the 'Update Status' tab."
    )

    # --- ID Loading Logic ---
    ids_loaded_from_sidebar = False

    if fetch_cv_btn:
        if cvid_input and cvid_input.strip().isdigit():
            # (CV Fetch logic remains the same)
            effective_creds = get_effective_credentials()
            if effective_creds:
                try:
                    with st.spinner(f"Fetching CV {cvid_input}..."):
                        token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                        token = get_access_token(**token_creds)
                        leads = fetch_records(token, cvid=cvid_input.strip(), fields=['id'], api_domain=effective_creds['api_domain'], fetch_all=fetch_all_pages)

                    if leads:
                        ids = [str(l['id']) for l in leads if str(l.get('id', '')).isdigit()]
                        unique_ids = sorted(list(set(ids)))
                        st.session_state.ids_text_area_content = "\n".join(unique_ids)
                        st.success(f"Fetched {len(unique_ids)} IDs from CV. Review below.")
                        ids_loaded_from_sidebar = True
                        st.session_state.lead_data_df = None
                    else:
                        st.warning("No leads found in the Custom View.")
                        st.session_state.ids_text_area_content = ""
                        st.session_state.loaded_lead_ids = []
                except Exception as e:
                    st.error(f"Fetch error: {e}"); logging.exception("CV fetch failed")
                    st.session_state.ids_text_area_content = ""
                    st.session_state.loaded_lead_ids = []
            else:
                st.error("Credentials missing.")
        else:
            st.error("Invalid CV ID.")

    if ids_loaded_from_sidebar:
        st.rerun()

# ----- Main Area: Tabs for Update / View ------------------------------------
# (Rest of the main area code remains identical to v3.9)
st.header("⚙️ Actions")
tab1, tab2 = st.tabs(["Update Lead Status", "View Lead Data"])

# --- Update Status Tab ---
with tab1:
    st.subheader("Update Lead Status")
    st.markdown("Paste Lead IDs below (one per line) or load them using the sidebar options.")

    st.text_area(
        "Lead IDs to Update:",
        key='ids_text_area_content', # Bind widget state to session state
        height=250,
        placeholder="Paste numeric Lead IDs here, one per line...",
        on_change=sync_ids_from_text_area, # Sync session state on text area change
        help="Enter one numeric Zoho Lead ID per line."
    )

    st.caption(f"IDs loaded (from text area): **{len(st.session_state.loaded_lead_ids)}**")

    rows_to_process = [{"id": i, "status": target_status_default} for i in st.session_state.loaded_lead_ids]

    col1_main_update, col2_main_update = st.columns([3, 1])
    with col1_main_update:
        st.write(f"Target Status: `{target_status_default}`")
    with col2_main_update:
        run_update_btn = st.button(f"🚀 Update {len(rows_to_process)} Records",
            disabled=not rows_to_process, type="primary", use_container_width=True, key="run_update_main_btn")

    # --- Confirmation Flow & Execution Block ---
    if run_update_btn:
        if rows_to_process: st.session_state['confirm_pending'] = True; st.rerun()
        else: st.warning("No valid IDs to process.")

    if st.session_state.get('confirm_pending', False):
        st.warning(f"Confirm status update for **{len(rows_to_process)}** records to '{target_status_default}'. This is irreversible.", icon="⚠️")
        confirm_col1, confirm_col2, _ = st.columns([1, 1, 3])
        if confirm_col1.button("Confirm & Proceed", type="primary", key="confirm_yes"):
            st.session_state['confirm_pending'] = False; st.session_state['execute_update'] = True; st.rerun()
        if confirm_col2.button("Cancel Update", key="confirm_no"):
            st.session_state['confirm_pending'] = False; st.info("Update cancelled."); st.rerun()

    if st.session_state.get('execute_update', False):
        st.session_state['execute_update'] = False # Reset flag
        st.subheader("📊 Update Results")
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
            results = bulk_update(rows_to_process, progress_hook=progress_hook, module=MODULE_API_NAME, **effective_creds)
            prog_container.progress(1.0, text="Update process complete!")
        except Exception as exc:
            st.error(f"Critical Failure: {exc}"); logging.exception("Bulk update failed"); prog_container.empty(); st.stop()

        end_time = datetime.now(); duration = end_time - start_time
        st.caption(f"Total processing time: {duration}")

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
                display_cols.append(col)

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

# --- View Lead Data Tab ---
with tab2:
    # (Identical to v3.8)
    st.subheader("View Lead Data")
    st.markdown("Load Lead IDs using the sidebar or paste into the **Update Lead Status** tab, then select fields below and fetch the data.")
    st.info(f"Lead IDs currently loaded: **{len(st.session_state.loaded_lead_ids)}** (from text area)")

    # --- Field Fetching and Selection ---
    fetch_fields_btn = st.button("Show/Refresh Available Lead Fields", key="fetch_fields_view")
    if fetch_fields_btn:
        st.session_state['lead_fields_df'] = None
        st.session_state['field_label_map'] = {}

    if fetch_fields_btn or st.session_state.get('lead_fields_df') is not None:
        if st.session_state.get('lead_fields_df') is None:
            try:
                effective_creds = get_effective_credentials();
                if not effective_creds: st.stop()
                with st.spinner(f"Fetching fields for {MODULE_API_NAME}..."):
                    token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                    token = get_access_token(**token_creds)
                    fields = get_module_fields(token, module=MODULE_API_NAME, api_domain=effective_creds['api_domain'])

                if fields:
                    df_fields = pd.DataFrame(fields)[['api_name', 'field_label', 'data_type']].sort_values('field_label')
                    st.session_state['lead_fields_df'] = df_fields
                    st.session_state['field_label_map'] = pd.Series(df_fields.api_name.values, index=df_fields.field_label).to_dict()
                    st.success(f"Fetched {len(df_fields)} fields.")
                    st.rerun()
                else: st.warning("No field data returned."); st.session_state['lead_fields_df'] = pd.DataFrame(); st.session_state['field_label_map'] = {}
            except Exception as e:
                st.error(f"Fetch fields error: {e}"); logging.exception("Field fetch error")

        # --- Field Selection UI ---
        if st.session_state.get('lead_fields_df') is not None and not st.session_state.lead_fields_df.empty:
            st.markdown("---")
            st.subheader("📊 Select Fields to View")
            available_labels = st.session_state.lead_fields_df['field_label'].tolist()
            st.session_state.selected_field_labels = st.multiselect(
                "Select fields:",
                options=available_labels,
                default=st.session_state.get('selected_field_labels', []),
                key="field_multiselect",
                help="Choose the columns you want to see in the table."
            )

            selected_api_names = [st.session_state.field_label_map.get(label) for label in st.session_state.selected_field_labels if st.session_state.field_label_map.get(label)]
            if 'id' not in selected_api_names:
                 selected_api_names.insert(0, 'id')

            st.caption(f"Selected {len(st.session_state.selected_field_labels)} fields ({len(selected_api_names)} API names including 'id').")

            # --- Fetch Data Button ---
            can_fetch_data = bool(st.session_state.loaded_lead_ids) and bool(st.session_state.selected_field_labels)
            if st.button("Fetch Selected Lead Data", disabled=not can_fetch_data, type="primary", key="fetch_lead_data_btn"):
                if not st.session_state.loaded_lead_ids: st.warning("Load Lead IDs first (using sidebar or paste area)."); st.stop()
                if not selected_api_names or (len(selected_api_names) == 1 and selected_api_names[0] == 'id'):
                    st.warning("Select at least one field to view (besides ID)."); st.stop()

                effective_creds = get_effective_credentials();
                if not effective_creds: st.stop()

                try:
                    token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                    token = get_access_token(**token_creds)

                    total_ids_to_fetch = len(st.session_state.loaded_lead_ids)
                    with st.spinner(f"Fetching data for {total_ids_to_fetch} leads..."):
                         all_fetched_data = fetch_records(
                             token,
                             module=MODULE_API_NAME,
                             ids=st.session_state.loaded_lead_ids,
                             fields=selected_api_names,
                             api_domain=effective_creds['api_domain']
                         )

                    if all_fetched_data:
                        st.session_state['lead_data_df'] = pd.DataFrame(all_fetched_data)
                        present_cols = set(st.session_state['lead_data_df'].columns)
                        for api_name in selected_api_names:
                            if api_name not in present_cols:
                                st.session_state['lead_data_df'][api_name] = None
                        st.session_state['lead_data_df'] = st.session_state['lead_data_df'][selected_api_names]
                        st.success(f"Successfully fetched data for {len(all_fetched_data)} records.")
                    else:
                        st.warning("No data returned for the selected leads and fields.")
                        st.session_state['lead_data_df'] = pd.DataFrame(columns=selected_api_names)

                except Exception as e:
                    st.error(f"Failed to fetch lead data: {e}")
                    logging.exception("Lead data fetch failed.")
                    st.session_state['lead_data_df'] = None

        # --- Display Data Table ---
        if st.session_state.get('lead_data_df') is not None:
            st.markdown("---")
            st.subheader("📋 Lead Data")
            display_df = st.session_state.lead_data_df.copy()
            st.dataframe(display_df, use_container_width=True)
            try:
                csv_data = display_df.to_csv(index=False).encode('utf-8')
                ts_data = datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")
                st.download_button(
                    f"Download Displayed Data ({len(display_df)} rows)",
                    csv_data,
                    f"lead_data_{ts_data}.csv",
                    "text/csv",
                    key="dl_lead_data"
                )
            except Exception as e:
                 st.error(f"CSV download prep failed: {e}")


# ----- Footer ----------------------------------------------------------------
# (Footer remains the same as v3.8)
st.divider()
with st.expander("ℹ️  Help & About"):
    st.markdown(textwrap.dedent(f"""
        **Zoho CRM Lead Utility v3.10**

        Two main functions available via the tabs above:

        **1. Update Lead Status:**
           - Updates the '{FIELD_TO_UPDATE}' field for '{MODULE_API_NAME}' records.
           - Load Lead IDs (TXT, CV, Paste).
           - Select target status (sidebar).
           - Review IDs in the text area.
           - Execute & Confirm. View results table, download failures.

        **2. View Lead Data:**
           - View specific data fields for loaded leads.
           - Load Lead IDs (TXT, CV, Paste into 'Update Status' tab's text area).
           - Click 'Show/Refresh Available Lead Fields'.
           - Select the desired fields from the multiselect list.
           - Click 'Fetch Selected Lead Data'.
           - View data in the table below. Download the displayed data.

        *Credentials:* Use `.env` or sidebar override for API access.
        """))