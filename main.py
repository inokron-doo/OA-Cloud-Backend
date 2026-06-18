from pathlib import Path
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

BACKEND_ROOT = Path(__file__).resolve().parent
BACKEND_SRC = BACKEND_ROOT / "src"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from src.api.auth_router import router
from src.api.weather_router import weather_router
from src.services.weather_scheduler import weather_scheduler
from src.services.feed_monitor import feed_monitor
from src.services.feeding_event_generator import feeding_event_generator
from src.api.barns_router import barns_router
from src.api.feed_router import feed_router
from src.api.farm_calendar_proxy import router as calendar_router
from src.api.moohero_router import moohero_router
from src.services.moohero_event_processor import moohero_event_processor
from src.api.anchor_router import router as anchor_router

app = FastAPI(
    title="Inokron Backend API",
    description=(
        "REST API for the Inokron livestock farm-management platform.\n\n"
        "Covers feed monitoring and alerting, heat-stress prediction, weather data, "
        "animal health (MooHero collar integration), farm calendar synchronisation, "
        "and IoT device management.\n\n"
        "**Base path:** All endpoints are served under `/api/v1`.\n\n"
        "**Authentication:** All endpoints except `/api/v1/login/`, `/api/v1/register/`, "
        "`/api/v1/forgot-password/`, and `/api/v1/reset-password/` require a JWT Bearer token "
        "obtained from `POST /api/v1/login/`. Pass it as `Authorization: Bearer <token>` "
        "or as an `access_token` cookie.\n\n"
        "**Errors:** Raised errors return `{\"error\": \"<message>\"}`; request-validation "
        "failures return FastAPI's default `{\"detail\": [...]}` (HTTP 422).\n\n"
        "**Content negotiation:** Observation, alert, and weather endpoints additionally "
        "serve OCSM-compliant JSON-LD when the request includes "
        "`Accept: application/ld+json`.\n\n"
        "**Interactive docs:** [Swagger UI](/api/docs) · [ReDoc](/api/redoc)"
    ),
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.max_request_size = 200 * 1024 * 1024


def _cors_settings():
    """Resolve allowed CORS origins from the CORS_ORIGINS env var.

    - Unset  -> sensible local-dev defaults (the Vite dev server and localhost).
      In the Docker deploy the frontend nginx proxies /api to the backend, so
      requests are same-origin and CORS is not involved there.
    - Comma-separated list -> those exact origins, with credentials enabled.
    - "*"    -> wildcard, but with credentials DISABLED, because the CORS spec
      forbids combining a wildcard origin with credentials (browsers reject it).
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return (
            ["http://localhost:5173", "http://localhost:3000", "http://localhost"],
            True,
        )
    if raw == "*":
        return ["*"], False
    return [o.strip() for o in raw.split(",") if o.strip()], True


_cors_origins, _cors_allow_credentials = _cors_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routing ---------------------------------------------------------------
# The entire API is served under a single versioned prefix, /api/v1, so the
# surface can evolve behind a new version prefix without breaking integrators.
# The frontend points at /api/v1 (see Inokron-frontend/src/config.ts).
API_V1 = "/api/v1"

app.include_router(router, tags=["Auth"], prefix=API_V1)
app.include_router(feed_router, tags=["Feed"], prefix=API_V1)
app.include_router(barns_router, tags=["Barns & Farms"], prefix=API_V1)
app.include_router(weather_router, tags=["Weather"], prefix=API_V1)
app.include_router(calendar_router, tags=["Farm Calendar"], prefix=f"{API_V1}/farm-calendar")
app.include_router(moohero_router, tags=["MooHero"], prefix=API_V1)
app.include_router(anchor_router, prefix=API_V1)


@app.on_event("startup")
async def startup_event():
    print("Starting Inokron Backend...")
    
    weather_scheduler.start()
    print(f"Weather scheduler started (interval: {weather_scheduler.forecast_interval_minutes} minutes)")
    
    feed_monitor.start()
    print("Alert monitor started (checking every 15 minutes)")
    
    await feeding_event_generator.start()
    print("Feeding event generator started (weekly event generation)")
    
    moohero_event_processor.start()
    print(f"MooHero event processor started (syncing every {moohero_event_processor.sync_interval_hours} hours)")
    


@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down Inokron Backend...")
    weather_scheduler.stop()
    feed_monitor.stop()
    await feeding_event_generator.stop()
    moohero_event_processor.stop()
    print("Services stopped")


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health", tags=["Health"], summary="Liveness probe")
async def health():
    """Liveness check for load balancers and orchestrators.

    Returns 200 with basic service info whenever the process is up. Does not
    check downstream dependencies (DB, weather/prediction services).
    """
    return {"status": "ok", "service": "inokron-backend", "version": app.version}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)