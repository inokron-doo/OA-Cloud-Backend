# Inokron Backend API

REST API for the Inokron livestock farm-management platform.
Interactive docs are auto-generated at runtime:

- **Swagger UI** → `http://<host>:8080/api/docs`
- **ReDoc** → `http://<host>:8080/api/redoc`
- **OpenAPI JSON** → `http://<host>:8080/api/openapi.json`

## Base path & versioning

All endpoints are served under **`/api/v1`** (e.g. `GET /api/v1/farms`).

The paths in the tables below are relative to the `/api/v1` base.

## Health

`GET /health` — unauthenticated liveness probe. Returns
`{"status": "ok", "service": "inokron-backend", "version": "1.0.0"}`. Does not check
downstream dependencies.

---

## Authentication

All endpoints require a JWT Bearer token except the four public auth endpoints:
`POST /api/v1/register/`, `POST /api/v1/login/`, `POST /api/v1/forgot-password/`, `POST /api/v1/reset-password/`.

### 1 — Register

```bash
curl -s -X POST http://localhost:8080/api/v1/register/ \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "email": "alice@example.com", "password": "secret"}'
```

### 2 — Login

```bash
curl -s -X POST http://localhost:8080/api/v1/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret"}'
```

Response:
```json
{
  "access_token": "<JWT>",
  "refresh_token": "<JWT>",
  "token_type": "bearer",
  "user": { "id": 1, "username": "alice", "email": "alice@example.com", ... }
}
```

| Token | Lifetime | Use |
|---|---|---|
| `access_token` | 500 minutes | Bearer header or `access_token` cookie |
| `refresh_token` | 30 days | Exchange for a new access token |

The `access_token` is also set as an httpOnly `access_token` cookie on the login
response. The Farm Calendar SSO flow uses this cookie rather than the Bearer header;
all other callers should prefer the header.

### 3 — Use the token

```bash
export TOKEN="<access_token from login>"

curl -s http://localhost:8080/api/v1/farms \
  -H "Authorization: Bearer $TOKEN"
```

### 4 — Refresh

```bash
curl -s -X POST http://localhost:8080/api/v1/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'
```

Returns a new `access_token` (and renews the cookie). Returns 401 if the refresh
token is expired or blacklisted.

### 5 — Logout

```bash
curl -s -X POST http://localhost:8080/api/v1/logout/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'
```

Blacklists the refresh token. The access token remains valid until its natural expiry.

---

## Content Negotiation (JSON-LD / OCSM)

Several observation, alert, and weather endpoints support
[OCSM](https://ocsm.github.io/)-compliant JSON-LD output. Add the header:

```
Accept: application/ld+json
```

Endpoints that support this:
- `GET /api/v1/feed/levels`
- `GET /api/v1/feed/alerts`, `GET /api/v1/feed/alerts/new`
- `GET /api/v1/feeding-locations/{id}/history`
- `GET /api/v1/weather/current/`
- `GET /api/v1/weather/{barn_id}/history`
- `GET /api/v1/weather/{barn_id}/forecast`
- `GET /api/v1/heat-stress/{barn_id}/status`
- `GET /api/v1/heat-stress/{barn_id}/feeding-predictions` *(deprecated)*
- `GET /api/v1/heat-stress/{barn_id}/predictions` *(deprecated)*

---

## Common Error Codes

| Status | Meaning |
|---|---|
| 400 | Bad request — invalid input (see `detail`) |
| 401 | Missing or expired/invalid token |
| 404 | Resource not found |
| 409 | Conflict (e.g. duplicate username, deleting a location with telemetry) |
| 502 | Upstream service error (weather service or prediction microservice) |
| 500 | Internal server error |

Raised errors have the shape `{"error": "<message>"}`. Request-validation failures
(e.g. a missing required field) return FastAPI's default `{"detail": [...]}` with
HTTP 422.

---

## Endpoint Groups

### Auth (`/api`)

| Method | Path | Description |
|---|---|---|
| POST | `/register/` | Register a new user |
| POST | `/login/` | Obtain access + refresh tokens |
| POST | `/logout/` | Blacklist refresh token |
| POST | `/validate_token/` | Check token validity (no auth required) |
| POST | `/token/refresh/` | Get a new access token |
| POST | `/forgot-password/` | Send password-reset email |
| POST | `/reset-password/` | Apply reset token + new password |
| GET | `/me/` | Return current user profile |

---

### Barns & Farms (`/api`)

| Method | Path | Description |
|---|---|---|
| GET | `/farms` | List all farms |
| GET | `/farms/{farm_id}` | Get a single farm |
| GET | `/farms/{farm_id}/barns` | List barns in a farm |
| GET | `/barns/{barn_id}` | Get a single barn (includes lat/lon) |
| GET | `/feeding-locations` | List all feeding locations (all barns) |
| GET | `/{barn_id}/feeding-locations` | List feeding locations in a barn |
| PUT | `/feeding-locations/{id}` | Rename / toggle visibility |
| PATCH | `/feeding-locations/{id}/visibility` | Show or hide |
| DELETE | `/feeding-locations/{id}` | Delete (409 if telemetry exists) |
| GET | `/feeding-locations/{id}/history` | Telemetry + feeding events history |

Feeding locations are **discovered automatically** from IoT device telemetry.
There is no manual create-by-name endpoint.

---

### Feed (`/api/v1/feed`, `/api/v1/schedules`)

#### Telemetry & Levels
| Method | Path | Description |
|---|---|---|
| GET | `/feed/levels` | Latest reading per feeding location |

#### Device Mapping
| Method | Path | Description |
|---|---|---|
| GET | `/feed/devices` | List devices with mappings |
| POST | `/feed/devices/link` | Assign device to barn |
| POST | `/feed/devices/location-mappings` | Map raw location name → location UUID |
| POST | `/feed/devices/barn-mappings` | Map raw barn name → barn UUID |
| GET | `/feed/devices/location-mappings` | List location mappings |
| GET | `/feed/devices/barn-mappings` | List barn mappings |
| GET | `/feed/devices/incoming-location-names` | Raw location strings seen recently |
| GET | `/feed/devices/incoming-barn-names` | Raw barn strings seen recently |

#### Thresholds
| Method | Path | Description |
|---|---|---|
| GET | `/feed/thresholds` | Global thresholds (defaults + overrides) |
| PUT | `/feed/thresholds` | Set global threshold overrides |
| GET | `/feed/feeding-locations/{id}/thresholds` | Resolved per-location thresholds |
| PUT | `/feed/feeding-locations/{id}/thresholds` | Set per-location overrides |

#### Alerts

Alerts are produced by one unified rule engine. Each alert carries `origin`
(`observed` = real-time, fired on current state | `predicted` = forecast, fired on
projected state) and, for predicted alerts, `predicted_for` (the forecast time the
condition is expected). Real-time and predicted alerts are independent records.

| Method | Path | Description |
|---|---|---|
| GET | `/feed/alerts` | List alerts (filterable) |
| GET | `/feed/alerts/new` | Active alerts. `?origin=observed` (default) \| `predicted` \| `all` |
| GET | `/feed/alerts/{id}` | Single alert |
| PUT | `/feed/alerts/{id}/resolve` | Mark resolved |
| DELETE | `/feed/alerts/clear` | Bulk resolve/delete. `?origin=observed` scopes to real-time alerts (predicted are engine-managed and would reappear) |

#### Alert settings
Per-rule configuration plus the global notification routing, stored in the
`alert_thresholds` key/value store (global, with per-feeding-location overrides for
numeric thresholds). Routing is per-severity: every alert always displays; the map
chooses which severities also email (`{"critical": true, "warning": true, "info": false}`).

| Method | Path | Description |
|---|---|---|
| GET | `/feed/alert-settings` | Per-rule config (`enabled`, `prediction_enabled`, `prediction_horizon_hours`, `notify_on_predict`) + `notification_routing` + `debounce_cycles` |
| PUT | `/feed/alert-settings` | Update rule config / routing / debounce (send only the keys to change) |

#### Schedules
| Method | Path | Description |
|---|---|---|
| POST | `/schedules` | Create recurring schedule + generate events |
| GET | `/schedules` | List schedules |
| GET | `/schedules/{id}` | Single schedule |
| PUT | `/schedules/{id}` | Update schedule |
| DELETE | `/schedules/{id}` | Deactivate (soft delete) |
| POST | `/schedules/{id}/generate-events` | Manually regenerate calendar events |
| POST | `/schedules/sync-from-calendar` | Sync from Farm Calendar |
| POST | `/feed/one-time-activity` | Create a one-off feeding event |

#### Forecast
| Method | Path | Description |
|---|---|---|
| GET | `/feed/feeding-locations/{id}/forecast` | Feed-level forecast (preferred) |
| POST | `/predict/feed-level` | Feed-level forecast (JSON body: `barn_id`, `feeding_location_id`, `horizon_hours`) |
| GET | `/feed/prediction-settings` | Prediction model settings |
| PUT | `/feed/prediction-settings` | Update prediction model settings |

---

### Weather & Heat Stress (`/api`)

THI (Temperature-Humidity Index) is computed for all weather data and forecast points.

| Method | Path | Description |
|---|---|---|
| GET | `/weather/current/` | Live weather at lat/lon |
| GET | `/weather/{barn_id}/history` | Historical observations (optional `bucket_minutes`, default 60, sets the actuals resolution — e.g. 15 or 30 for a finer series) |
| GET | `/weather/{barn_id}/forecast` | 5-day hourly forecast (max 120 h) |
| GET | `/heat-stress/{barn_id}/status` | Current THI level + alarm flags |
| GET | `/heat-stress/{barn_id}/feeding-predictions` | **Deprecated** — R1 predicted feed-intake drop; superseded by predicted `heat_stress` alerts via `GET /feed/alerts/new?origin=all` |
| GET | `/heat-stress/{barn_id}/predictions` | **Deprecated** — R2 severe heat-stress forecast; superseded by predicted `heat_stress` alerts |
| GET | `/weather/scheduler/status` | Scheduler state |
| POST | `/weather/scheduler/start` | Start auto-fetch |
| POST | `/weather/scheduler/stop` | Stop auto-fetch |
| POST | `/weather/scheduler/interval` | Set fetch interval (1–1440 min) |
| POST | `/weather/fetch-now` | Immediate fetch for all barns |

Heat stress severity levels: `normal` / `mild` / `moderate` / `severe` / `emergency`.
The `/heat-stress/{barn_id}/status` response includes boolean edge-parameter flags
that IoT devices can use to trigger cooling systems automatically.

---

### Animals / MooHero (`/api`)

Requires MooHero credentials in env (`MOOHERO_CLIENT_ID`, `MOOHERO_CLIENT_SECRET`).
Returns 502 if credentials are invalid.

| Method | Path | Description |
|---|---|---|
| GET | `/moohero/farms` | MooHero farms with local link status |
| POST | `/moohero/farm-links` | Link MooHero farm to local farm |
| DELETE | `/moohero/farm-links/{moohero_farm_id}` | Remove link |
| GET | `/moohero/farm-mappings` | All mapping records |
| GET | `/moohero/farms/{farm_id}/animals` | Animals in a MooHero farm (live) |
| GET | `/moohero/events` | Health events live from MooHero |
| GET | `/moohero/events/stored` | Health events from local cache |
| GET | `/moohero/events/by-collars` | Cached events by collar ID list |
| GET | `/moohero/alerts` | Health-spike alerts (the unified rate-based `health_spike` replaced per-animal alerts; `animal_id` scope reads live from MooHero) |
| GET | `/animals` | Registered animals (local DB) |
| POST | `/animals` | Register an animal |
| GET | `/animals/{id}` | Animal detail + event history |
| PUT | `/animals/{id}` | Update animal fields |
| GET | `/animals/barn-stats` | Per-barn animal count + event totals |

---

### Farm Calendar (`/api/v1/farm-calendar`)

Proxies to and integrates with the Farm Calendar service.

| Method | Path | Description |
|---|---|---|
| GET | `/` | SSO redirect (browser-only) |
| GET | `/calendar` | Proxy Farm Calendar main page |
| GET | `/activities` | List calendar activities |
| POST | `/activities` | Create one or more activities |
| DELETE | `/activities/{id}` | Delete an activity |
| GET | `/activity-types` | Get Feeding activity type UUID |
| POST | `/activity-types` | Create a new activity type |

---

### Settings (`/api/v1/anchor-time`)

| Method | Path | Description |
|---|---|---|
| GET | `/anchor-time/` | Get day-start anchor time |
| PUT | `/anchor-time/` | Set day-start anchor time (`HH:MM` or `HH:MM:SS`) |

The anchor time defines when the farmer's day starts and is used to align
all historical data windows and alert analysis periods.

---

## Prediction Microservice

Feed-level forecasting is handled by a separate microservice running on port **8015**.
The main backend proxies `/feed/feeding-locations/{id}/forecast` and
`/predict/feed-level` to it. If the microservice is down, these endpoints
return 502. The microservice is configured via the `PREDICTION_SERVICE_URL` env var.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | JWT signing key (required) |
| `DATABASE_URL` | — | PostgreSQL connection string |
| `WEATHER_SERVICE_URL` | `http://127.0.0.1:8004` | Weather microservice base URL |
| `WEATHER_SERVICE_USERNAME` | `test` | Weather service auth username |
| `WEATHER_SERVICE_PASSWORD` | `test` | Weather service auth password |
| `PREDICTION_SERVICE_URL` | `http://127.0.0.1:8015` | Feed prediction microservice base URL |
| `FARM_CALENDAR_URL` | `http://localhost:8002` | Farm Calendar service base URL |
| `MOOHERO_CLIENT_ID` | — | MooHero API client ID |
| `MOOHERO_CLIENT_SECRET` | — | MooHero API client secret |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated allowed origins. `*` = wildcard (credentials disabled). |
| `SMTP_*` | — | Mail settings for password-reset emails |

Copy `.env.example` to `.env` and fill in the required values before starting.
