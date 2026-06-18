Prediction service for feed forecasts.

This is a **pure forecaster**: it returns the projected feed-level timeline
(`result.forecast`: `[{time, level_percent}]`), applied refills, and
`estimated_empty_at`. It no longer computes alerts — the main backend's unified
rule engine runs the same thresholds over this forecast timeline to emit predicted
alerts (`result.alerts` is always empty and is retained only for response-shape
compatibility).

Run locally:
- Create a .env with DATABASE_URL
- Install requirements
- Start: uvicorn app.main:app --host 0.0.0.0 --port 8015

The main backend should call this service internally.
