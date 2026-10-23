# CBP Form 7512 PDF Editor

A Streamlit app that clears the marked values in one-page CBP Form 7512 PDFs and places shipment details at the numbered locations. Select a client and destination, enter the shipment details once, and apply them to one or more portrait Letter-size forms. Multiple results download together as a ZIP.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run pdf_app.py
```

## Deploy to Streamlit Community Cloud

This repository and app are public. `client_consignees.json` contains the client, destination, and consignee directory used by the app. Publish only while this disclosure is approved.

Create an app from this repository, select the `main` branch, and use `pdf_app.py` as the entrypoint. Choose a client, enter that client's three-character destination code, and select a matching consignee. The entire original Consignee text area is cleared while its underline is preserved. Replacement text uses a fixed 7 pt font, wraps to two lines, and is truncated with an ellipsis if it is longer. The selected CN/HK foreign port is also copied into the Last foreign port field. Enter shipment details once for all uploaded PDFs; a single result downloads as a PDF and multiple results download together as a ZIP. The app processes uploads in memory and does not write them to the app server's disk. Do not commit shipment-specific PDFs or local secrets to this repository.
