# Zoho CRM Lead-Status Bulk Updater (Streamlit UI - v3.4)

This Streamlit web application allows users to bulk-update the "Lead Status" field for records in the Zoho CRM Leads module. It provides a user-friendly interface for loading Lead IDs, selecting a target status, and executing the update via the Zoho API v8.

## Features

*   **Bulk Updates:** Update the status of hundreds or thousands of leads efficiently.
*   **Flexible ID Input:**
    *   Paste IDs directly into the text area.
    *   Upload a `.txt` file containing one numeric Lead ID per line.
    *   Fetch Lead IDs directly from a Zoho Custom View by providing its ID (supports pagination).
*   **Interactive Status Selection:** Choose the target lead status from a dropdown list.
*   **Credential Management:**
    *   Securely uses credentials from a local `.env` file (recommended).
    *   Optionally override `.env` credentials via the sidebar for the current session (secrets are masked).
*   **Robust API Handling:**
    *   Updates sent in batches (default 100).
    *   Automatic retries with backoff for rate limits and server errors.
*   **Detailed Feedback:**
    *   Real-time progress bar.
    *   Results table showing success/failure for each ID.
*   **Metadata Fetching:** View and download available Lead module field names.
*   **Logging:** Detailed logs written to `zoho_bulk.log`.

## Project Structure

```
lead_status_updater/
├── .env
├── .gitignore
├── README.md
├── requirements.txt
├── zoho_bulk.py
└── streamlit_app.py
```

## Setup

1.  **Clone/Download:** Get the project files.
2.  **Python Environment:** Python 3.9+ recommended. Use a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate   # Windows: .venv\Scripts\activate
    ```
3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure Credentials:**
    *   Copy `.env.template` to `.env`.
    *   Fill in `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` in `.env`.
    *   **(Optional)** Set `ZOHO_API_DOMAIN`, `ZOHO_ACCOUNTS_URL` in `.env` for non-US regions.
    *   **Keep `.env` secure and out of Git.**

## Running the App

1.  Activate your virtual environment.
2.  Navigate to the project directory.
3.  Run: `streamlit run streamlit_app.py`
4.  Open the URL provided (usually `http://localhost:8501`).

## Usage Guide

1.  **(Optional) Credentials:** Use sidebar expander to override `.env` for this session.
2.  **Target Status:** Select the desired `Lead_Status` in the sidebar.
3.  **Load Lead IDs:** Use *one* sidebar method: Upload TXT File, Fetch from CV ID, or Paste into main text area.
4.  **Review IDs:** Check/edit the list in the main text area.
5.  **Execute:** Click **Update**, then **Confirm Update**.
6.  **View Results:** Check summary/table.

---
