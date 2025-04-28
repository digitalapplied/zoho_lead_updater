# Zoho CRM Lead-Status Bulk Updater

Bulk-change the **Lead_Status** field on any list of Lead IDs without leaving
your browser.

| Feature | Detail |
|---------|--------|
| **Upload or paste IDs** | TXT file (one ID per line) *or* paste into the text box |
| **Fetch from Custom View** | Supply Zoho CV ID – supports multi-page fetch |
| **Credential override** | Masked inputs in sidebar; `.env` is default |
| **Progress bar** | Live per-chunk reporting |
| **Diagnostics** | IDs that Zoho skips are tagged *NOT_FOUND* or *PERMISSION_DENIED* |
| **Field explorer** | Click to list/download all Lead field API names |

---

## Quick start (local)

```bash
git clone <this-repo> zoho_lead_updater && cd $_
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.template .env                # add your Zoho creds
streamlit run streamlit_app.py
```

Open `http://localhost:8501` and go.

---

## Deployment on Streamlit Cloud

1. Push these files to GitHub.  
2. In **Secrets**, add your `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`,
   `ZOHO_REFRESH_TOKEN` (and `ZOHO_API_DOMAIN` if EU/IN/AU).  
3. Click **Deploy**.

---

© 2025 Digital Applied
