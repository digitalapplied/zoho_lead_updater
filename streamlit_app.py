#!/usr/bin/env python3
"""
streamlit_app.py  ·  v3.2
TXT-only lead loader with CV fetch, credential override and progress bar.
"""

import logging, math, textwrap
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from zoho_bulk import (
    VALID_STATUSES, bulk_update, fetch_leads_by_cvid, get_module_fields,
    get_access_token, CHUNK_SIZE,
    DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_REFRESH_TOKEN,
    DEFAULT_API_DOMAIN, DEFAULT_ACCOUNTS_URL, MODULE_API_NAME
)

# -- Streamlit page --
st.set_page_config("Zoho Lead Updater", "🛠️", layout="wide")
load_dotenv()
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ───────────────────────── helpers ───────────────────────────────────────────
def logo():
    local = Path(__file__).with_name("logo.png")
    if local.exists():
        st.image(str(local), width=160); return
    try:
        st.image("https://raw.githubusercontent.com/digitalapplied/assets/main/da_logo.png", width=160)
    except: pass

def parse_ids(txt): return sorted({ln.strip() for ln in txt.splitlines() if ln.strip().isdigit()})

def creds():
    return dict(
        client_id     = st.session_state.cid or DEFAULT_CLIENT_ID,
        client_secret = st.session_state.csec or DEFAULT_CLIENT_SECRET,
        refresh_token = st.session_state.rtok or DEFAULT_REFRESH_TOKEN,
        api_domain    = st.session_state.domain,
        accounts_url  = st.session_state.accurl
    )

# ───────────────────────── session defaults ─────────────────────────────────
for k,val in (("cid",""),("csec",""),("rtok",""),
              ("domain",DEFAULT_API_DOMAIN),("accurl",DEFAULT_ACCOUNTS_URL),
              ("ids",""),("fields",None)):
    st.session_state.setdefault(k,val)

# ───────────────────────── sidebar ───────────────────────────────────────────
with st.sidebar:
    logo()
    st.header("🔐 Credentials")
    with st.expander("Override .env for this session", False):
        st.text_input("Client ID", key="cid")
        st.text_input("Client Secret", type="password", key="csec")
        st.text_input("Refresh Token", type="password", key="rtok")
        st.text_input("API Domain", key="domain")
        st.text_input("Accounts URL", key="accurl")
    st.divider()

    st.header("① Default Lead Status")
    default_status = st.selectbox("Status",
                                  VALID_STATUSES,
                                  index=VALID_STATUSES.index("Junk Lead"),
                                  label_visibility="collapsed")

    st.divider()
    st.header("② Load Lead IDs")
    up = st.file_uploader("TXT file (one ID per line)", type="txt")
    cvid = st.text_input("…or Custom-View ID")
    fetch_all = st.checkbox("Fetch all pages", True)
    fetch = st.button("Fetch IDs", disabled=not cvid.strip().isdigit())

# TXT upload ------------------------------------------------------------------
if up:
    st.session_state.ids = up.read().decode()
    st.toast("File loaded ✔", icon="📄")

# CV fetch --------------------------------------------------------------------
if fetch:
    try:
        token = get_access_token(**{k:v for k,v in creds().items() if k!="api_domain"})
        recs  = fetch_leads_by_cvid(token, cvid.strip(),
                                    api_domain=creds()["api_domain"],
                                    fetch_all=fetch_all)
        st.session_state.ids = "\n".join(sorted({str(r["id"]) for r in recs if "id" in r}))
        st.success(f"{len(parse_ids(st.session_state.ids))} IDs fetched")
    except Exception as e:
        st.error(e)

# ───────────────────────── main pane ─────────────────────────────────────────
st.title("🛠️ Zoho Lead-Status Bulk Updater")

ids_text = st.text_area("③ Review IDs & Execute",
                        value=st.session_state.ids,
                        height=240)
ids = parse_ids(ids_text)
st.caption(f"{len(ids)} unique numeric IDs detected.")

if st.button(f"🚀 Update {len(ids)} records", disabled=not ids):
    bar = st.progress(0.0, text="Starting…")
    rows = [{"id": i, "status": default_status} for i in ids]
    total_chunks = max(1, math.ceil(len(rows)/CHUNK_SIZE))
    def hook(done): bar.progress(done/total_chunks, f"Chunk {done}/{total_chunks}")
    start = datetime.utcnow()
    try:
        res = bulk_update(rows, progress_hook=hook, **creds())
    except Exception as e:
        st.error(e); st.stop()
    bar.empty()

    df = pd.DataFrame(res)[["id","status","code","message"]]
    ok, bad = (df.status=="success").sum(), (df.status!="success").sum()
    st.markdown(f"<b style='color:#28a745'>✅ {ok}</b> | <b style='color:#dc3545'>❌ {bad}</b>",
                unsafe_allow_html=True)
    st.dataframe(df, height=300, use_container_width=True)
    if bad:
        st.download_button("Download failures CSV",
                           df[df.status!="success"].to_csv(index=False),
                           f"fail_{datetime.utcnow():%Y%m%d_%H%M%S}.csv",
                           "text/csv")

# field list ------------------------------------------------------------------
st.divider()
if st.button("Show Lead field names"):
    if st.session_state.fields is None:
        try:
            token = get_access_token(**{k:v for k,v in creds().items() if k!="api_domain"})
            f = get_module_fields(token, api_domain=creds()["api_domain"])
            st.session_state.fields = pd.DataFrame(f)[["api_name","field_label","data_type"]]
        except Exception as e:
            st.error(e)
    if st.session_state.fields is not None:
        st.dataframe(st.session_state.fields, use_container_width=True)
        st.download_button("Download fields CSV",
                           st.session_state.fields.to_csv(index=False),
                           "lead_fields.csv","text/csv")

st.divider()
with st.expander("ℹ️  Why an ID can show “missing in response”"):
    st.markdown(textwrap.dedent("""
        The Zoho bulk-update endpoint sometimes omits a record from the
        `data` array – commonly because the record is already in that status,
        has been deleted, or your token lacks permission to edit it.

        The app re-queries Zoho to label the row **NOT_FOUND** or
        **PERMISSION_DENIED** so you know what happened.
    """))
