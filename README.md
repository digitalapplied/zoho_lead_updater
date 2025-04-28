# Zoho CRM Lead Utility: Bulk Status Updater & Data Viewer

**Version:** (Inferred from code comments: `streamlit_app.py v3.10`, `zoho_bulk.py v3.4`)

## Overview

This application provides a user-friendly web interface (built with Streamlit) to interact with the Zoho CRM API (v8). Its primary function is to allow users to **bulk-update the `Lead_Status` field** for records within the **`Leads` module**. Additionally, it offers functionality to **fetch and view specific data fields** for a given set of Lead IDs.

It aims to streamline common, repetitive tasks that can be cumbersome through the standard Zoho CRM web interface, especially when dealing with large numbers of records. The application emphasizes secure credential handling, robust API interaction with error management, and clear feedback to the user.

## Core Functionality

The application is divided into two main functional tabs:

**1. Update Lead Status:**

*   **Bulk Updates:** Efficiently changes the `Lead_Status` field for potentially thousands of Zoho Leads simultaneously.
*   **Flexible Lead ID Input:**
    *   **Paste IDs:** Directly paste a list of numeric Lead IDs (one per line) into a text area. The application automatically cleans, deduplicates, and validates these IDs.
    *   **Fetch from Custom View (CV):** Provide the numeric ID of a Zoho CRM Custom View. The application fetches all Lead IDs belonging to that view, handling pagination automatically if requested (`Fetch all pages` option) to retrieve more than the default 200 records per page.
*   **Target Status Selection:** Choose the desired final `Lead_Status` from a predefined dropdown list (`VALID_STATUSES` configured in `zoho_bulk.py`).
*   **Confirmation Step:** Includes a mandatory confirmation prompt before executing the irreversible bulk update operation to prevent accidental changes.
*   **Batched API Calls:** Sends update requests to the Zoho API in manageable chunks (default: 100 records per request, defined by `CHUNK_SIZE` in `zoho_bulk.py`) to comply with API limits and improve reliability.
*   **Robust API Handling:**
    *   Implements automatic retries with exponential backoff for common transient API errors (e.g., rate limits `429`, server errors `5xx`).
    *   Handles specific API responses like `204 No Content`.
    *   Includes checks to identify records that were part of a sent batch but missing from the API's response.
*   **Detailed Results:**
    *   Displays a real-time progress bar during the update process.
    *   Presents a summary count of successful and failed updates.
    *   Shows a detailed results table with the status (`success` or `error`), API response code, message, and details for *each* processed Lead ID.
    *   Allows downloading a CSV file containing only the records that failed during the update process for further investigation or reprocessing.

**2. View Lead Data:**

*   **Data Retrieval:** Fetches specific field data for the Lead IDs currently loaded in the application (via pasting or CV fetch in the "Update Status" tab).
*   **Dynamic Field Selection:**
    *   Fetches the list of available fields for the `Leads` module directly from Zoho CRM (`get_module_fields` function).
    *   Allows the user to select multiple fields they wish to view using a multi-select dropdown.
    *   Displays field labels for user-friendliness but uses API names internally.
*   **Efficient Data Fetching:** Retrieves data for the selected Leads and fields using the Zoho API, handling chunking of Lead IDs (`IDS_PER_REQUEST` in `zoho_bulk.py`) if necessary for large lists.
*   **Data Display & Download:**
    *   Presents the fetched data in a clean, scrollable table.
    *   Provides a button to download the displayed table data as a CSV file.

**Common Features:**

*   **Credential Management:**
    *   Securely loads Zoho API credentials (`Client ID`, `Client Secret`, `Refresh Token`) from a local `.env` file by default.
    *   Allows users to *temporarily override* the `.env` credentials via the sidebar for the current session only. Overridden secrets (Client Secret, Refresh Token) are masked in the UI.
    *   Supports configuration for different Zoho data centers (e.g., US, EU, IN, AU) via `.env` or sidebar overrides (`API_DOMAIN`, `ACCOUNTS_URL`).
*   **Logging:** Records detailed information about API calls, successes, errors, retries, and application flow into a local file (`zoho_bulk.log`) for debugging and auditing purposes. Sensitive credentials are automatically scrubbed from logs.

## Application Flow

**A. Bulk Status Update Flow:**

1.  **Setup:** Ensure Python, dependencies (`requirements.txt`), and a configured `.env` file are ready.
2.  **Run App:** Execute `streamlit run streamlit_app.py` in the terminal.
3.  **Open UI:** Access the application in your web browser (usually `http://localhost:8501`).
4.  **(Optional) Override Credentials:** If needed for the current session, expand the "Zoho API Credentials" section in the sidebar and enter temporary credentials.
5.  **Select Target Status:** In the sidebar, choose the desired `Lead_Status` from the "Target Lead Status" dropdown.
6.  **Load Lead IDs:** Use *one* of the following methods in the sidebar/main area:
    *   **Paste:** Copy and paste numeric Lead IDs (one per line) into the main text area under the "Update Lead Status" tab. The list is automatically parsed and validated.
    *   **Fetch from CV:** Enter a valid numeric Custom View ID in the sidebar input, check/uncheck "Fetch all pages" as needed, and click "Fetch IDs from CV". The fetched IDs will populate the main text area.
7.  **Review IDs:** Verify the list of Lead IDs displayed in the main text area. The count of loaded IDs is shown below the text area.
8.  **Initiate Update:** Click the "🚀 Update [N] Records" button on the "Update Lead Status" tab.
9.  **Confirm Update:** Read the warning message carefully. Click "Confirm & Proceed" to start the bulk update or "Cancel Update" to abort.
10. **Monitor Progress:** Observe the progress bar as the application processes records in chunks.
11. **View Results:** Once complete, review the success/failure summary and the detailed results table.
12. **(Optional) Download Failures:** If any records failed, click the "Download [N] failed" button to get a CSV file of those specific records.

**B. View Lead Data Flow:**

1.  **Setup & Run App:** Same as steps 1-3 in the Update Flow.
2.  **(Optional) Override Credentials:** Same as step 4 in the Update Flow.
3.  **Load Lead IDs:** Use one of the methods described in step 6 of the Update Flow (Paste or Fetch from CV). The IDs need to be present in the main text area of the "Update Lead Status" tab.
4.  **Navigate to View Tab:** Click the "View Lead Data" tab.
5.  **Fetch Available Fields:** Click the "Show/Refresh Available Lead Fields" button. The app will query Zoho for all fields in the `Leads` module.
6.  **Select Fields:** Once fields are loaded, use the "Select fields:" multi-select dropdown to choose the specific fields you want to retrieve data for. (`id` is always included implicitly if not selected).
7.  **Fetch Data:** Click the "Fetch Selected Lead Data" button. The application will query the Zoho API for the selected fields for all loaded Lead IDs.
8.  **View Data:** Examine the fetched data displayed in the table.
9.  **(Optional) Download Data:** Click the "Download Displayed Data" button to save the table contents as a CSV file.

## Technical Details

*   **Frontend:** Streamlit (`streamlit`)
*   **Backend Logic/API Interaction:** Python (`requests`, `python-dotenv`)
*   **Zoho API Version:** v8 (based on URL structure in `zoho_bulk.py`)
*   **Target Module:** `Leads` (configurable via `MODULE_API_NAME` in `zoho_bulk.py`)
*   **Target Field (for Update):** `Lead_Status` (configurable via `FIELD_TO_UPDATE` in `zoho_bulk.py`)
*   **Authentication:** Zoho OAuth 2.0 (using Refresh Token grant type)
*   **API Call Strategy:**
    *   Updates: Batched PUT requests (Chunk size: `CHUNK_SIZE`)
    *   Record Fetch (by ID): Batched GET requests (Chunk size: `IDS_PER_REQUEST`)
    *   Record Fetch (by CV): Paginated GET requests (Page size: `PER_PAGE`)
*   **Error Handling:** Retries with exponential backoff (`MAX_RETRY`, `BACKOFF`), specific status code checks, detailed logging.

## Directory Structure

```
digitalapplied-zoho_lead_updater/
├── README.md           # This detailed readme file
├── requirements.txt    # Python package dependencies
├── streamlit_app.py    # Main Streamlit application UI and flow logic
├── zoho_bulk.py        # Handles all Zoho API communication, data processing, auth
└── .env.template       # Template for environment variables (Zoho credentials)
# --- Generated Files (after running) ---
├── .env                # Copied from .env.template, contains your actual credentials (KEEP PRIVATE!)
└── zoho_bulk.log       # Log file for API interactions and errors
```

## Setup Instructions

1.  **Prerequisites:**
    *   Python 3.9 or higher recommended.
    *   Access to a terminal or command prompt.
    *   `git` (optional, for cloning).
    *   Valid Zoho CRM API Credentials (Client ID, Client Secret, Refresh Token). See Zoho API documentation for how to generate these.

2.  **Clone or Download:**
    *   **Git:** `git clone <repository_url>`
    *   **Download:** Download the source code ZIP file and extract it.

3.  **Navigate to Project Directory:**
    ```bash
    cd digitalapplied-zoho_lead_updater
    ```

4.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv .venv
    # Activate the environment:
    # Windows:
    .\.venv\Scripts\activate
    # macOS/Linux:
    source .venv/bin/activate
    ```

5.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

6.  **Configure Credentials:**
    *   Copy the template file: `cp .env.template .env` (or copy manually).
    *   **Edit the `.env` file:** Open `.env` in a text editor.
    *   Replace the placeholder values with your actual Zoho API credentials:
        *   `ZOHO_CLIENT_ID=your_actual_client_id`
        *   `ZOHO_CLIENT_SECRET=your_actual_client_secret`
        *   `ZOHO_REFRESH_TOKEN=your_actual_refresh_token`
    *   **(Optional)** If your Zoho account is *not* in the US data center, uncomment and set the correct `ZOHO_API_DOMAIN` and `ZOHO_ACCOUNTS_URL` for your region (e.g., `.eu`, `.com.au`, `.in`).
    *   **SECURITY:** Keep the `.env` file **secure and private**. Do **not** commit it to version control (a `.gitignore` file should ideally exclude `.env`).

## Running the Application

1.  **Activate Virtual Environment:** Make sure your virtual environment (e.g., `.venv`) is activated (see Setup step 4).
2.  **Navigate to Directory:** Ensure your terminal is in the `digitalapplied-zoho_lead_updater` directory.
3.  **Run Streamlit:**
    ```bash
    streamlit run streamlit_app.py
    ```
4.  **Access App:** Streamlit will output URLs (Network and Local). Open the local URL (usually `http://localhost:8501`) in your web browser.

## Usage Guide

1.  **(Credentials):** Ensure `.env` is configured OR use the sidebar expander ("Zoho API Credentials") to enter temporary credentials for the session.
2.  **(Load IDs):**
    *   **Update Tab:** Paste IDs into the text area OR use the sidebar "Fetch IDs from CV" option.
    *   **View Tab:** Relies on IDs loaded via the "Update Tab" methods.
3.  **(Update Flow):**
    *   Select the target `Lead_Status` in the sidebar.
    *   Review IDs in the text area.
    *   Click "Update Records", then "Confirm & Proceed".
    *   Check the results table. Download failures if needed.
4.  **(View Data Flow):**
    *   Navigate to the "View Lead Data" tab.
    *   Click "Show/Refresh Available Lead Fields".
    *   Select desired fields from the multiselect dropdown.
    *   Click "Fetch Selected Lead Data".
    *   View the data table. Download if needed.

## Configuration (`.env` file)

*   `ZOHO_CLIENT_ID`: (Required) Your Zoho API Console Client ID.
*   `ZOHO_CLIENT_SECRET`: (Required) Your Zoho API Console Client Secret.
*   `ZOHO_REFRESH_TOKEN`: (Required) A valid Zoho OAuth 2.0 Refresh Token with the necessary scopes (e.g., `ZohoCRM.modules.leads.READ`, `ZohoCRM.modules.leads.UPDATE`, `ZohoCRM.settings.fields.READ`).
*   `ZOHO_API_DOMAIN`: (Optional) The base URL for API calls (e.g., `https://www.zohoapis.eu`). Defaults to `https://www.zohoapis.com` if not set.
*   `ZOHO_ACCOUNTS_URL`: (Optional) The URL for exchanging the refresh token (e.g., `https://accounts.zoho.eu/oauth/v2/token`). Defaults to `https://accounts.zoho.com/oauth/v2/token` if not set.

## Error Handling & Logging

*   The application attempts to handle common API errors gracefully through retries.
*   Specific error messages from the Zoho API are displayed in the results table for failed records.
*   UI messages guide the user through required steps and potential issues (e.g., missing credentials, no IDs loaded).
*   Detailed logs, including API requests/responses (with sensitive data scrubbed) and error stack traces, are written to `zoho_bulk.log` in the application directory. Check this file for troubleshooting.

## Limitations & Considerations

*   **API Limits:** Zoho CRM imposes API rate limits. While the app uses batching and retries, extremely large updates might still hit daily limits. Monitor your Zoho API usage dashboard.
*   **Irreversible Updates:** The status update operation is **irreversible** through this tool. Always double-check the Lead IDs and target status before confirming.
*   **Credential Security:** Protecting your `.env` file and the Refresh Token is crucial. Avoid sharing them or committing them to public repositories.
*   **Scope Requirements:** The Refresh Token used must have the appropriate Zoho API scopes enabled to read/update leads and read field settings.
*   **Field/Module Names:** The application currently targets the `Leads` module and `Lead_Status` field. Modifying this requires changes in `zoho_bulk.py` (`MODULE_API_NAME`, `FIELD_TO_UPDATE`, `VALID_STATUSES`).