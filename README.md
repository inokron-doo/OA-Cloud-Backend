# SFS SmartFeed Backend

Central REST API and data layer of the **SmartFeed Feed Monitoring System (SFS)**,
developed by **Inokron d.o.o.** under the EU-funded **OpenAgri** project (SIP13, a
European Union co-funded pilot).

It ingests telemetry from edge devices, stores it in PostgreSQL/TimescaleDB, exposes
a versioned REST API to the frontend and integrators, runs background services for
feed monitoring and alerting, and integrates external services (a feed-level
prediction microservice, MooHero animal-health collars, OpenAgri Farm Calendar, and
OpenAgri Weather).

- **Version:** v1.0.0
- **Language:** Python 3.12 (FastAPI)
- **Licence:** [AGPL-3.0](LICENSE)
- **Base path:** all endpoints under `/api/v1`


## Architecture

FastAPI application (`main.py`) mounting routers from `src/api/` and starting
background services from `src/services/` (feed monitor, feeding-event generator,
weather scheduler, MooHero event processor) via APScheduler. Data is persisted in
*PostgreSQL/TimescaleDB*; schema is managed by *Alembic* migrations
(`migrations/`). A separate FastAPI microservice (`prediction_service/`) performs
feed-level forecasting and is called internally over HTTP.

```
edge / Azure IoT Hub → ingest → TimescaleDB → REST API (+ JSON-LD) → frontend / integrators
                                                  ├── prediction_service (HTTP)
                                                  ├── OpenAgri Farm Calendar (SSO)
                                                  ├── OpenAgri Weather
                                                  └── MooHero API
```

## Quick start

The preferred way to install and run the full platform (this service plus its
database, prediction service, calendar and weather service) is the
[`OA-Cloud-Deploy`](https://github.com/inokron-doo/OA-Cloud-Deploy) docker-compose
stack — see its
[`INSTALLATION.md`](https://github.com/inokron-doo/OA-Cloud-Deploy/blob/main/INSTALLATION.md)
for complete, end-to-end instructions including Azure IoT Hub setup. It runs
migrations and starts the prediction service automatically.

For standalone development only, to run the backend directly:

```bash
cp .env.example .env          # configure DB, JWT secret, service URLs/keys
pip install -r requirements.txt
alembic upgrade head          # apply database migrations
uvicorn main:app --host 0.0.0.0 --port 8080
```

- Interactive docs: `/api/docs` (Swagger) · `/api/redoc` (ReDoc) · `/api/openapi.json`
- Health probe: `GET /health`
- Hand-written API reference with curl examples: [`API.md`](API.md)

## Authentication

Obtain a JWT via `POST /api/v1/login/` and pass it as `Authorization: Bearer <token>`
or an `access_token` cookie. The four public endpoints are `register`, `login`,
`forgot-password`, and `reset-password`.

## Configuration

All configuration is via environment variables — see [`.env.example`](.env.example)
and the `OA-Cloud-Deploy` repo.


## Licence

**AGPL-3.0** — see [LICENSE](LICENSE). Because the backend is provided as a network
service, anyone running a modified version and offering it to users over a network
must make the complete corresponding source available under the same licence.

## Contact

Inokron d.o.o., Kranj, Slovenia — info@inokron.com

---

*Funded by the European Union under the OpenAgri project (SIP13).*
