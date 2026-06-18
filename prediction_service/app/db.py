from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from app.config import get_settings


class PredictionDB:
    def __init__(self) -> None:
        settings = get_settings()
        self._dsn = settings.database_url
        self._pool = None

    @contextmanager
    def connection(self):
        conn = psycopg2.connect(self._dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_feeding_location(self, feeding_location_id: str) -> Optional[Dict[str, Any]]:
        sql = (
            "SELECT feeding_location_id, barn_id, name, external_id "
            "FROM feeding_locations "
            "WHERE feeding_location_id = %s "
            "LIMIT 1;"
        )
        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (feeding_location_id,))
                return cur.fetchone()

    def get_feeding_location_by_source_key(
        self, barn_id: str, source_key: str
    ) -> Optional[Dict[str, Any]]:
        sql = (
            "SELECT feeding_location_id, barn_id, name, external_id "
            "FROM feeding_locations "
            "WHERE barn_id = %s "
            "AND (" \
            "    LOWER(name) = LOWER(%s) "
            "    OR LOWER(external_id) = LOWER(%s) "
            ") "
            "LIMIT 1;"
        )
        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (barn_id, source_key, source_key))
                return cur.fetchone()

    def load_feed_history(
        self, feeding_location_id: str, history_hours: int
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT "
            "    q.time, "
            "    q.device_eui, "
            "    q.device_id, "
            "    q.barn_id, "
            "    q.feeding_location_id, "
            "    q.reading_kind, "
            "    q.numeric_value, "
            "    q.temperature, "
            "    q.humidity, "
            "    CASE "
            "        WHEN q.temperature IS NOT NULL AND q.humidity IS NOT NULL THEN ROUND( "
            "            ( "
            "                ((q.temperature * 9.0 / 5.0) + 32.0) "
            "                - (0.55 - (0.0055 * q.humidity)) "
            "                * (((q.temperature * 9.0 / 5.0) + 32.0) - 58.0) "
            "            )::numeric, "
            "            2 "
            "        ) "
            "        ELSE NULL "
            "    END AS thi, "
            "    q.raw "
            "FROM ( "
            "    SELECT "
            "        tr.time, "
            "        tr.device_eui, "
            "        tr.device_id, "
            "        tr.barn_id, "
            "        tr.feeding_location_id, "
            "        tr.reading_kind, "
            "        tr.numeric_value, "
            "        COALESCE(tr.temperature, climate_match.temperature) AS temperature, "
            "        COALESCE(tr.humidity, climate_match.humidity) AS humidity, "
            "        tr.raw "
            "    FROM telemetry_readings tr "
            "    LEFT JOIN LATERAL ( "
            "        SELECT "
            "            c.temperature, "
            "            c.humidity "
            "        FROM telemetry_readings c "
            "        WHERE c.reading_kind = 'climate' "
            "          AND c.barn_id::text = tr.barn_id::text "
            "          AND c.time BETWEEN tr.time - INTERVAL '30 minutes' "
            "                         AND tr.time + INTERVAL '30 minutes' "
            "        ORDER BY ABS(EXTRACT(EPOCH FROM (c.time - tr.time))) "
            "        LIMIT 1 "
            "    ) AS climate_match ON TRUE "
            "    WHERE tr.feeding_location_id = %s "
            "      AND tr.reading_kind = 'feed_level_percentage' "
            "      AND tr.time >= NOW() - (%s * INTERVAL '1 hour') "
            "      AND tr.numeric_value IS NOT NULL "
            ") AS q "
            "ORDER BY q.time ASC;"
        )
        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (feeding_location_id, history_hours))
                return list(cur.fetchall())

    def load_calendar_feeding_activities(
        self, barn_id: str, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT "
            "    a.id AS activity_id, "
            "    a.title, "
            "    a.start_datetime, "
            "    a.end_datetime, "
            "    a.details, "
            "    a.parcel_id AS barn_id "
            "FROM farm_activities_farmcalendaractivity a "
            "JOIN farm_activities_farmcalendaractivitytype t "
            "    ON a.activity_type_id = t.id "
            "WHERE t.name = 'Feeding' "
            "  AND a.parcel_id = %s "
            "  AND a.start_datetime >= %s "
            "  AND a.start_datetime <= %s "
            "ORDER BY a.start_datetime ASC;"
        )
        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (barn_id, start_date, end_date))
                return list(cur.fetchall())

    def create_prediction_settings_table(self) -> None:
        table_sql = (
            "CREATE TABLE IF NOT EXISTS prediction_settings ("
            "    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
            "    scope_type text NOT NULL,"
            "    scope_id uuid NULL,"
            "    key text NOT NULL,"
            "    value jsonb NOT NULL,"
            "    updated_by integer NULL,"
            "    created_at timestamp without time zone DEFAULT now(),"
            "    updated_at timestamp without time zone DEFAULT now()"
            ");"
        )
        index_sql = (
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "prediction_settings_scope_key_idx "
            "ON prediction_settings ("
            "    scope_type, "
            "    COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid), "
            "    key"
            ");"
        )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(table_sql)
                cur.execute(index_sql)

    def get_prediction_settings(
        self, scope_type: str, scope_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if scope_id is None:
            sql = (
                "SELECT scope_type, scope_id, key, value, updated_by, created_at, "
                "updated_at "
                "FROM prediction_settings "
                "WHERE scope_type = %s AND scope_id IS NULL "
                "ORDER BY key ASC;"
            )
            params = (scope_type,)
        else:
            sql = (
                "SELECT scope_type, scope_id, key, value, updated_by, created_at, "
                "updated_at "
                "FROM prediction_settings "
                "WHERE scope_type = %s AND scope_id = %s "
                "ORDER BY key ASC;"
            )
            params = (scope_type, scope_id)

        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def upsert_prediction_settings(
        self,
        scope_type: str,
        scope_id: Optional[str],
        settings_data: Dict[str, Any],
        updated_by: Optional[int] = None,
    ) -> None:
        if not settings_data:
            return

        update_sql = (
            "UPDATE prediction_settings "
            "SET value = %s, updated_by = %s, updated_at = now() "
            "WHERE scope_type = %s "
            "  AND key = %s "
            "  AND (scope_id = %s OR (scope_id IS NULL AND %s IS NULL));"
        )
        insert_sql = (
            "INSERT INTO prediction_settings (scope_type, scope_id, key, value, updated_by) "
            "SELECT %s, %s, %s, %s, %s "
            "WHERE NOT EXISTS ("
            "    SELECT 1 FROM prediction_settings "
            "    WHERE scope_type = %s "
            "      AND key = %s "
            "      AND (scope_id = %s OR (scope_id IS NULL AND %s IS NULL))"
            ");"
        )

        with self.connection() as conn:
            with conn.cursor() as cur:
                for key, value in settings_data.items():
                    cur.execute(
                        update_sql,
                        (
                            psycopg2.extras.Json(value),
                            updated_by,
                            scope_type,
                            key,
                            scope_id,
                            scope_id,
                        ),
                    )
                    cur.execute(
                        insert_sql,
                        (
                            scope_type,
                            scope_id,
                            key,
                            psycopg2.extras.Json(value),
                            updated_by,
                            scope_type,
                            key,
                            scope_id,
                            scope_id,
                        ),
                    )


db = PredictionDB()
