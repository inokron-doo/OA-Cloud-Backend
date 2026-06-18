"""Reconcile the IoT ingest schema with scripts/iot_ingest.py.

The live (Neon) database had been hand-patched beyond what the migrations
captured: scripts/iot_ingest.py writes a `thi` column on telemetry_readings
and a raw-archive table `iot_telemetry`, neither of which any earlier
migration created. On a fresh database the parsed-telemetry INSERT failed
(missing `thi` column) and the raw archive INSERT failed (missing table).

This migration adds both so a fresh deployment matches the ingest code.
All statements are idempotent (IF NOT EXISTS) so it can also be applied
safely to the existing production database without erroring if a piece is
already present.

- telemetry_readings.thi : precomputed Temperature-Humidity Index sent by the
  edge device. Nullable; not read by the backend today (derivable from
  temperature + humidity) but stored as delivered.
- iot_telemetry          : write-only raw archive of every incoming IoT Hub
  message ({body, enqueued_time, properties, sequence_number}).
"""
from alembic import op

revision = '032'
down_revision = 'b17fa9de7ab9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE telemetry_readings ADD COLUMN IF NOT EXISTS thi double precision;"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS iot_telemetry (
            id         bigserial PRIMARY KEY,
            device_id  text,
            data       jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_iot_telemetry_device_time "
        "ON iot_telemetry (device_id, created_at DESC);"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_iot_telemetry_device_time;")
    op.execute("DROP TABLE IF EXISTS iot_telemetry;")
    op.execute("ALTER TABLE telemetry_readings DROP COLUMN IF EXISTS thi;")
