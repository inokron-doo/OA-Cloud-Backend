import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from azure.eventhub.aio import EventHubConsumerClient
import psycopg2
from psycopg2 import pool
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()

IOT_HUB_CONNECTION_STRING = os.getenv("IOT_HUB_CONNECTION_STRING")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

connection_pool = None
message_count = 0
error_count = 0


def init_connection_pool():
    global connection_pool
    try:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL
        )
        logger.info("Database connection pool initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize connection pool: {e}")
        return False


def get_db_connection():
    global connection_pool
    if connection_pool is None:
        if not init_connection_pool():
            raise RuntimeError("Database connection pool is not available")

    conn = connection_pool.getconn()
    if conn.closed:
        try:
            connection_pool.putconn(conn, close=True)
        except Exception:
            pass
        conn = connection_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        try:
            connection_pool.putconn(conn, close=True)
        except Exception:
            pass
        conn = connection_pool.getconn()

    return conn


def return_db_connection(conn):
    if connection_pool is None or conn is None:
        return
    try:
        if conn.closed:
            connection_pool.putconn(conn, close=True)
        else:
            connection_pool.putconn(conn)
    except Exception:
        pass


def table_exists(table_name):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        row = cur.fetchone()
        cur.close()
        return bool(row and row[0])
    except Exception as e:
        logger.error(f"Error checking table existence for {table_name}: {e}")
        return False
    finally:
        if conn:
            return_db_connection(conn)


def table_has_column(table_name, column_name):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name)
        )
        has_col = cur.fetchone() is not None
        cur.close()
        return has_col
    except Exception as e:
        logger.error(f"Error checking column {table_name}.{column_name}: {e}")
        return False
    finally:
        if conn:
            return_db_connection(conn)


def reset_connection_pool():
    global connection_pool
    try:
        if connection_pool is not None:
            connection_pool.closeall()
    except Exception as e:
        logger.warning(f"Failed to close existing connection pool cleanly: {e}")
    connection_pool = None
    return init_connection_pool()


def _parse_iso_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def _resolve_reading_timestamp(reading, body, enqueued_time):
    raw_candidates = [
        reading.get("timestamp"),
        reading.get("time"),
        body.get("timestamp") if isinstance(body, dict) else None,
        enqueued_time,
    ]
    for candidate in raw_candidates:
        parsed = _parse_iso_timestamp(candidate)
        if parsed:
            return parsed
    return datetime.now(timezone.utc)


def _normalize_key(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_present(*values):
    for value in values:
        normalized = _normalize_key(value)
        if normalized:
            return normalized
    return None


def _normalize_lookup_key(value):
    normalized = _normalize_key(value)
    return normalized.lower() if normalized else None




def insert_raw(device_eui, data):
    global message_count, error_count
    for attempt in (1, 2):
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO iot_telemetry (device_id, data)
                VALUES (%s, %s)
                """,
                (device_eui, Json(data))
            )

            conn.commit()
            message_count += 1
            logger.info(f"RAW STORED | Device={device_eui} | Total={message_count}")
            return True

        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt == 1:
                logger.warning(f"RAW insert DB connection issue, resetting pool and retrying once: {e}")
                reset_connection_pool()
                continue
            error_count += 1
            logger.error(f"Error inserting RAW after retry: {e}")
            return False
        except Exception as e:
            error_count += 1
            logger.error(f"Error inserting RAW: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                return_db_connection(conn)


def get_device_mapping_by_eui(device_eui):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            if table_has_column("devices", "barn_id"):
                cur.execute(
                    """
                    SELECT d.device_id, d.barn_id, d.feeding_location_id
                    FROM devices d
                    WHERE d.device_eui = %s
                    LIMIT 1
                    """,
                    (device_eui,)
                )
            else:
                cur.execute(
                    """
                    SELECT d.device_id, NULL::uuid AS barn_id, d.feeding_location_id
                    FROM devices d
                    WHERE d.device_eui = %s
                    LIMIT 1
                    """,
                    (device_eui,)
                )
        except Exception as e:
            if 'barn_id' in str(e) and 'does not exist' in str(e):
                conn.rollback()
                cur.execute(
                    """
                    SELECT d.device_id, NULL::uuid AS barn_id, d.feeding_location_id
                    FROM devices d
                    WHERE d.device_eui = %s
                    LIMIT 1
                    """,
                    (device_eui,)
                )
            else:
                raise
        result = cur.fetchone()
        cur.close()
        if result:
            return result[0], result[1], result[2]
        return None, None, None
    except Exception as e:
        logger.error(f"Error looking up device mapping: {e}")
        return None, None, None
    finally:
        if conn:
            return_db_connection(conn)


def create_device(device_eui):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            if table_has_column("devices", "barn_id"):
                cur.execute(
                    """
                    INSERT INTO devices (device_id, device_eui, barn_id, feeding_location_id, display_name)
                    VALUES (gen_random_uuid(), %s, NULL, NULL, %s)
                    RETURNING device_id
                    """,
                    (device_eui, device_eui)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO devices (device_id, device_eui, feeding_location_id, display_name)
                    VALUES (gen_random_uuid(), %s, NULL, %s)
                    RETURNING device_id
                    """,
                    (device_eui, device_eui)
                )
        except Exception as e:
            if 'barn_id' in str(e) and 'does not exist' in str(e):
                conn.rollback()
                cur.execute(
                    """
                    INSERT INTO devices (device_id, device_eui, feeding_location_id, display_name)
                    VALUES (gen_random_uuid(), %s, NULL, %s)
                    RETURNING device_id
                    """,
                    (device_eui, device_eui)
                )
            else:
                raise
        result = cur.fetchone()
        conn.commit()
        cur.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error creating device: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            return_db_connection(conn)


def get_barn_name_by_id(barn_id):
    conn = None
    try:
        normalized = _normalize_key(barn_id)
        if not normalized:
            return None
        conn = get_db_connection()
        cur = conn.cursor()
        has_name = table_has_column("farm_management_farmparcel", "name")
        if has_name:
            cur.execute(
                """
                SELECT COALESCE(identifier, name)
                FROM farm_management_farmparcel
                WHERE id = %s
                LIMIT 1
                """,
                (normalized,)
            )
        else:
            cur.execute(
                """
                SELECT identifier
                FROM farm_management_farmparcel
                WHERE id = %s
                LIMIT 1
                """,
                (normalized,)
            )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error looking up barn name by id: {e}")
        return None
    finally:
        if conn:
            return_db_connection(conn)


def get_feeding_location_by_barn_and_external(barn_id, eui_key):
    """
    Barn-scoped lookup. Checks `eui` first, then `external_id` fallback.
    """
    conn = None
    try:
        normalized = _normalize_key(eui_key)
        if not barn_id or not normalized:
            return None

        conn = get_db_connection()
        cur = conn.cursor()
        has_eui = table_has_column("feeding_locations", "eui")

        if has_eui:
            cur.execute(
                """
                SELECT feeding_location_id
                FROM feeding_locations
                WHERE barn_id = %s
                  AND (
                        eui = %s
                        OR LOWER(external_id) = LOWER(%s)
                        OR feeding_location_id::text = %s
                      )
                LIMIT 1
                """,
                (barn_id, normalized, normalized, normalized),
            )
        else:
            cur.execute(
                """
                SELECT feeding_location_id
                FROM feeding_locations
                WHERE barn_id = %s
                  AND (
                        LOWER(external_id) = LOWER(%s)
                        OR feeding_location_id::text = %s
                      )
                LIMIT 1
                """,
                (barn_id, normalized, normalized),
            )

        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error looking up feeding location in barn: {e}")
        return None
    finally:
        if conn:
            return_db_connection(conn)

def ensure_discovered_feeding_location(barn_id, eui_key):
    """
    Find or create a feeding location for the given barn + device EUI key.

    eui_key  - the immutable device-sent string (e.g. "feeding_0").
    name     - set to eui_key at creation; user may rename it later.
    external_id - kept equal to eui_key for backwards compat.
    """
    conn = None
    try:
        if not barn_id or not eui_key:
            return None

        normalized_key = str(eui_key).strip()
        if not normalized_key:
            return None

        existing = get_feeding_location_by_barn_and_external(barn_id, normalized_key)
        if existing:
            return existing

        conn = get_db_connection()
        cur = conn.cursor()

        has_eui = table_has_column("feeding_locations", "eui")
        has_external_id = table_has_column("feeding_locations", "external_id")
        has_is_hidden = table_has_column("feeding_locations", "is_hidden")

        new_location_id = str(uuid.uuid4())

        columns = ["feeding_location_id", "barn_id", "name"]
        values = [new_location_id, barn_id, normalized_key]

        if has_eui:
            columns.append("eui")
            values.append(normalized_key)

        if has_external_id:
            columns.append("external_id")
            values.append(normalized_key)

        if has_is_hidden:
            columns.append("is_hidden")
            values.append(False)

        cols_sql = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(values))

        cur.execute(
            f"""
            INSERT INTO feeding_locations ({cols_sql})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
            RETURNING feeding_location_id
            """,
            values
        )
        row = cur.fetchone()
        cur.close()
        conn.commit()

        if row:
            logger.info(
                "Auto-discovered feeding location | barn=%s eui=%s id=%s",
                barn_id,
                normalized_key,
                new_location_id,
            )
            return new_location_id

        # Insert was a no-op (race condition) - re-query
        return get_feeding_location_by_barn_and_external(barn_id, normalized_key)

    except Exception as e:
        if conn:
            conn.rollback()
        logger.warning(
            "Auto-discovery insert failed for barn=%s eui=%s, retrying lookup: %s",
            barn_id,
            eui_key,
            e,
        )
        return get_feeding_location_by_barn_and_external(barn_id, eui_key)
    finally:
        if conn:
            return_db_connection(conn)


def get_device_barn_mapping(device_id, source_barn_key):
    conn = None
    try:
        if not device_id or not source_barn_key:
            return None
        if not table_exists("device_barn_mappings"):
            return None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT barn_id
            FROM device_barn_mappings
            WHERE device_id = %s
              AND source_barn_key = %s
            LIMIT 1
            """,
            (device_id, str(source_barn_key).strip().lower())
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error looking up explicit device barn mapping: {e}")
        return None
    finally:
        if conn:
            return_db_connection(conn)


def insert_parsed_data(device_eui, data):
    global error_count
    for attempt in (1, 2):
        conn = None
        try:
            body = data.get("body", {})
            readings = body.get("readings", [])
            enqueued_time = data.get("enqueued_time")

            if not readings:
                logger.warning("No readings to parse")
                return False

            device_uuid, device_barn_id, device_location_id = get_device_mapping_by_eui(device_eui)
            if not device_uuid:
                device_uuid = create_device(device_eui)
                if not device_uuid:
                    logger.error(f"Cannot insert readings - device create failed: {device_eui}")
                    return False

            if not device_barn_id:
                logger.warning(
                    f"No barn linked for device {device_eui}; "
                    "will try barn_id from payload"
                )

            conn = get_db_connection()
            cur = conn.cursor()
            inserted_count = 0
            conflict_count = 0

            for r in readings:
                resolved_timestamp = _resolve_reading_timestamp(r, body, enqueued_time)

                reading_kind = r.get("reading_type")
                external_location_id = r.get("feeding_location_id")
                external_barn_id = _first_present(
                    r.get("barn_id"),
                    r.get("barnId"),
                    body.get("barn_id") if isinstance(body, dict) else None,
                    body.get("barnId") if isinstance(body, dict) else None,
                )
                external_barn_name = _first_present(
                    r.get("barn_name"),
                    r.get("barnName"),
                    r.get("barn"),
                    body.get("barn_name") if isinstance(body, dict) else None,
                    body.get("barnName") if isinstance(body, dict) else None,
                    body.get("barn") if isinstance(body, dict) else None,
                )
                external_location_name = _first_present(
                    r.get("feeding_location_name"),
                    r.get("feedingLocationName"),
                    r.get("location_name"),
                    body.get("feeding_location_name") if isinstance(body, dict) else None,
                    body.get("feedingLocationName") if isinstance(body, dict) else None,
                    body.get("location_name") if isinstance(body, dict) else None,
                )

                # ---- Resolve barn ----
                # Barns are assigned to devices explicitly in Setup. We never
                # guess a barn by matching incoming names against existing barns.
                barn_uuid = None
                barn_alias_key = external_barn_name or external_barn_id
                if barn_alias_key:
                    # explicit per-incoming-key mapping (one device -> several barns)
                    barn_uuid = get_device_barn_mapping(device_uuid, barn_alias_key)
                if not barn_uuid:
                    # otherwise the device's assigned barn (set in Setup)
                    barn_uuid = device_barn_id

                # ---- Resolve feeding location ----
                # Identity is the device-sent location key (external_location_id),
                # found-or-created within the resolved barn. The name is a display
                # label only and is never used to resolve a location.
                feeding_location_uuid = None
                if external_location_id and barn_uuid:
                    feeding_location_uuid = ensure_discovered_feeding_location(
                        barn_uuid,
                        external_location_id,
                    )
                elif device_location_id:
                    # device pinned to a single feeding location (readings carry no key)
                    feeding_location_uuid = device_location_id

                numeric_value = r.get("value")
                temperature = r.get("temperature")
                humidity = r.get("humidity")
                thi = r.get("thi")

                raw_payload = dict(r)
                raw_payload["timestamp"] = resolved_timestamp.isoformat()
                if external_barn_name:
                    raw_payload["barn_name"] = external_barn_name
                    raw_payload["incoming_barn_name"] = external_barn_name
                if external_location_name:
                    raw_payload["feeding_location_name"] = external_location_name
                if barn_uuid:
                    raw_payload["resolved_barn_name"] = get_barn_name_by_id(barn_uuid)

                logger.info(
                    "INGEST RESOLUTION | device=%s | incoming_barn=%s | resolved_barn=%s | incoming_location=%s | resolved_location=%s",
                    device_eui,
                    external_barn_name or external_barn_id,
                    raw_payload.get("resolved_barn_name"),
                    external_location_name or external_location_id,
                    feeding_location_uuid,
                )

                cur.execute(
                    """
                    INSERT INTO telemetry_readings (
                        time,
                        device_eui,
                        device_id,
                        barn_id,
                        feeding_location_id,
                        reading_kind,
                        numeric_value,
                        temperature,
                        humidity,
                        thi,
                        raw
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        resolved_timestamp,
                        device_eui,
                        device_uuid,
                        barn_uuid,
                        feeding_location_uuid,
                        reading_kind,
                        numeric_value,
                        temperature,
                        humidity,
                        thi,
                        Json(raw_payload)
                    )
                )

                if cur.rowcount == 1:
                    inserted_count += 1
                else:
                    conflict_count += 1

            conn.commit()
            logger.info(
                "PARSED %s readings from %s | inserted=%s conflicted=%s",
                len(readings),
                device_eui,
                inserted_count,
                conflict_count,
            )
            return True

        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt == 1:
                logger.warning(
                    f"Parsed insert DB connection issue, resetting pool and retrying once: {e}"
                )
                reset_connection_pool()
                continue
            error_count += 1
            logger.error(f"Error inserting parsed readings after retry: {e}")
            return False
        except Exception as e:
            error_count += 1
            logger.error(f"Error inserting parsed readings: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                return_db_connection(conn)


async def on_event(partition_context, event):
    try:
        body = json.loads(event.body_as_str())

        device_eui = event.system_properties.get(
            b"iothub-connection-device-id",
            b"unknown"
        ).decode("utf-8")

        logger.info(f"Incoming message | Device EUI={device_eui}")

        properties = {}
        if event.properties:
            for k, v in event.properties.items():
                if isinstance(k, bytes):
                    k = k.decode()
                if isinstance(v, bytes):
                    v = v.decode()
                properties[k] = v

        data = {
            "body": body,
            "enqueued_time": event.enqueued_time.isoformat(),
            "properties": properties,
            "sequence_number": event.sequence_number
        }

        insert_raw(device_eui, data)
        insert_parsed_data(device_eui, data)

    except Exception as e:
        logger.error(f"Error processing IoT message: {e}")


async def main():
    if not init_connection_pool():
        return

    if not IOT_HUB_CONNECTION_STRING:
        logger.error("IOT_HUB_CONNECTION_STRING is not set")
        return

    client = EventHubConsumerClient.from_connection_string(
        conn_str=IOT_HUB_CONNECTION_STRING,
        consumer_group="$Default"
    )

    logger.info("Listening for IoT Hub messages...")

    async with client:
        await client.receive(
            on_event=on_event,
            starting_position="-1"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
