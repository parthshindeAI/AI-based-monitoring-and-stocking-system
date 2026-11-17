# AI Monitoring and Stocking System

A Streamlit inventory application with persistent SQLite storage, CSV data import/export, stock-risk indicators, and an ML demand forecast.

## Features

- Dashboard with stock, inventory value, risk, and reorder recommendations
- Add, edit, delete, import, and export inventory records
- Import and export dated item-level sales history
- Per-item Random Forest demand forecast for a 7-day horizon when at least 28 calendar days of sales history are available
- Clearly labeled 7-day-average or entered-demand baseline when an ML forecast is not supported by enough history
- SQLite persistence by default; no database server is required

## Run locally

To enable sign-in, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, register an OIDC client with your identity provider, and replace the example values. The configured `redirect_uri` must exactly match the callback URL registered with the provider. The default example is for Google; for Microsoft Entra, Okta, or another OIDC provider, set `server_metadata_url` to that provider's discovery URL and use the matching client credentials.

The `[access].allowed_emails` list is required when sign-in is enabled. Only listed accounts can access inventory. Keep `secrets.toml` private; it is git-ignored and must never be committed.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app opens at `http://localhost:8501`.

## Run with Docker

Install Docker Desktop, then from the repository folder run:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edit .streamlit\secrets.toml with your OIDC provider and allowed email address.
docker compose up --build -d
```

The Compose setup mounts `.streamlit/secrets.toml` into the container. Configure the OIDC callback URL as `http://localhost:8501/oauth2callback`. Open `http://localhost:8501`. SQLite data is stored in the Compose-managed `inventory_data` volume and survives container restarts and rebuilds. To stop the app without deleting its data:

```powershell
docker compose down
```

To delete the container **and** its stored data, run `docker compose down --volumes`. This permanently removes the inventory and sales database.

## Data setup

On first run, sample inventory from `data/sample_data.csv` is loaded into `data/inventory.db`. Inventory changes and imported sales history remain in SQLite across restarts.

To use your own inventory, import a CSV with these columns:

`item_name,category,current_stock,reorder_point,daily_demand,lead_time_days,unit_price,supplier`

To train ML forecasts, import a sales CSV with these columns:

`date,item_name,quantity_sold`

Dates should be parseable by pandas and quantities must be non-negative. Each item can have one sales record per date. Missing dates are treated as zero sales, so provide complete daily records or ensure gaps really represent zero sales. For accurate forecasts, use real, representative sales history; demo data and the fallback estimate are not an ML forecast.

Set `INVENTORY_DATABASE_PATH` to use a different SQLite file location. Existing data is not automatically copied when changing this path.

## Current limitations

- Forecasts are item-level Random Forest regressors based on historical daily demand, lag features, and calendar features; they are not a guarantee of future demand.
- Items with less than 28 calendar days of history use a labeled baseline instead of being presented as ML predictions.
- The app supports OIDC sign-in and an email allow-list when `.streamlit/secrets.toml` is configured. Without that file, it runs in local development mode without sign-in.
- Restock email alerts are sent only when a signed-in user clicks the send button. Configure SMTP host, sender, and recipient in the private `[email]` section; SMTP credentials are optional if the relay does not require authentication. Port 465 uses implicit TLS; other ports use STARTTLS.
- The Docker Compose setup is for a single host. HTTPS/reverse proxy, a shared remote database, automated alert scheduling, and ERP integration still need deployment-specific configuration.
- Do not expose the app directly to the public internet without HTTPS and a carefully configured identity provider and access allow-list.
