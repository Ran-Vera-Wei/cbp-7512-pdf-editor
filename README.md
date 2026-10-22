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

Keep this repository private because `consignee_mapping.json` contains the consignee directory. In Streamlit Community Cloud, create an app from this repository, select the `main` branch, and use `pdf_app.py` as the entrypoint. A private repository keeps the deployed app private by default.

The app processes uploaded shipment PDFs in memory and does not write them to the app server's disk. Do not commit shipment-specific PDFs or local secrets to this repository.
