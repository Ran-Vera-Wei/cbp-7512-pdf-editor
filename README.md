# CBP Form 7512 PDF Editor

A Streamlit app that clears the marked values in a one-page CBP Form 7512 and places shipment details at the numbered locations. It supports portrait Letter-size forms matching the supplied layout.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run pdf_app.py
```

## Deploy to Streamlit Community Cloud

This repository and app are public. `consignee_mapping.json` contains the consignee directory, and the app exposes consignee choices derived from that file. Publish only while this disclosure is approved.

Create an app from this repository, select the `main` branch, and use `pdf_app.py` as the entrypoint. The app processes uploaded shipment PDFs in memory and does not write them to the app server's disk. Do not commit shipment-specific PDFs or local secrets to this repository.
