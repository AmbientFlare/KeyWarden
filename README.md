# KeyWarden

KeyWarden is a self-hosted software licensing service with a REST API, Python client SDK, and web administration interface. It supports license validation, activation and heartbeat tracking, product and client management, API keys, audit records, and optional hardware fingerprint checks.

## Requirements

- Docker Engine with the Compose plugin
- Python 3.10+ for local development
- PostgreSQL for the service database

## Run with Docker Compose

1. Copy `.env.example` to `.env`. Generate separate random hex values for `SECRET_KEY` and `POSTGRES_PASSWORD` with `openssl rand -hex 32`, then set a strong `ADMIN_PASSWORD`.
2. Start the services:

   ```sh
   docker compose up --build
   ```

3. Open the admin interface at <http://localhost:1777>. The API listens at <http://localhost:1776>.

Compose publishes the application ports on localhost by default. Set `APP_BIND=0.0.0.0` only when intentionally exposing the services on the host network. The database and Redis ports are not published.

## Local development

Create and activate a virtual environment, install dependencies, and configure the required environment variables:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(openssl rand -hex 32)"
export DATABASE_URL="postgresql://user:password@localhost/license_server"
python api_server.py
```

Run the admin interface separately with `python web_gui.py`. Run the API test suite with `python -m pytest tests`.

## Python client

`client_sdk.py` contains `LicenseClient` for applications integrating with a KeyWarden API. Configure its license key, API key, and server URL for your deployment; keep credentials out of source control.

## Security

Set unique secrets before starting the service. Use HTTPS through a trusted reverse proxy for non-local deployments, restrict administrative access, and back up the PostgreSQL database. Review the application configuration before exposing a deployment publicly.

## License

This project is licensed under the MIT License; see [LICENSE](LICENSE).
