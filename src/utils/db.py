import os
import logging
from contextlib import contextmanager
import json
import hashlib
import secrets
import base64
import psycopg2
from psycopg2 import pool, OperationalError
from psycopg2.extras import RealDictCursor, Json
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
GLOBAL_SCOPE_ID = "00000000-0000-0000-0000-000000000000"
class PGDB:
    _instance = None
    _pool = None
   
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
   
    def __init__(self):
        if PGDB._pool is not None:
            return
        if not os.getenv('DATABASE_URL'):
            return
        self._create_pool()

    def _ensure_pool(self):
        if PGDB._pool is not None:
            return
        connection_string = os.getenv('DATABASE_URL')
        if not connection_string:
            raise ValueError("DATABASE_URL is not configured")
        self._create_pool()
   
    def _create_pool(self):
        connection_string = os.getenv('DATABASE_URL')
        PGDB._pool = pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=20,
            dsn=connection_string,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            connect_timeout=10
        )
        logger.info("Database pool created")
   
    def _validate_connection(self, conn):
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except (OperationalError, psycopg2.InterfaceError):
            return False
   
    @contextmanager
    def get_connection_context(self):
        conn = None
        max_attempts = 3
        
        try:
            self._ensure_pool()
            for attempt in range(max_attempts):
                try:
                    conn = PGDB._pool.getconn()
                    
                    if not self._validate_connection(conn):
                        logger.warning(f"Stale connection detected, getting new one (attempt {attempt + 1})")
                        PGDB._pool.putconn(conn, close=True)
                        conn = None
                        
                        if attempt == max_attempts - 1:
                            raise OperationalError("Failed to get valid connection after maximum retry attempts")
                        
                        continue
                    
                    break  # Connection is valid, exit retry loop
                        
                except (OperationalError, psycopg2.InterfaceError) as e:
                    logger.error(f"Connection error on attempt {attempt + 1}: {e}")
                    if conn:
                        try:
                            PGDB._pool.putconn(conn, close=True)
                        except:
                            pass
                        conn = None
                    
                    if attempt == max_attempts - 1:
                        raise
            
            yield conn  # Yield OUTSIDE the for loop
            
        finally:
            if conn:
                try:
                    PGDB._pool.putconn(conn)
                except Exception as e:
                    logger.error(f"Error returning connection: {e}")
   
    def make_django_password(self, password: str) -> str:
        algorithm = 'pbkdf2_sha256'
        iterations = 600000
        salt = secrets.token_hex(8)
        
        hash_obj = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        hash_str = hash_obj.hex()
        
        return f"{algorithm}${iterations}${salt}${hash_str}"
    
    def verify_django_password(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt, hash_str = encoded.split('$')
            iterations = int(iterations)
            
            hash_obj = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                iterations
            )
            
            return hash_obj.hex() == hash_str
        except:
            return False
   
    def register_user(self, user_data):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT id FROM auth_user WHERE email = %s",
                        (user_data['email'],)
                    )
                    if cursor.fetchone():
                        raise ValueError("Email already registered")
                   
                    cursor.execute(
                        "SELECT id FROM auth_user WHERE username = %s",
                        (user_data['username'],)
                    )
                    if cursor.fetchone():
                        raise ValueError("Username already registered")
                   
                    hashed_password = self.make_django_password(user_data['password'])
                   
                    cursor.execute("""
                        INSERT INTO auth_user (
                            username, email, password, first_name, last_name,
                            is_active, is_staff, is_superuser, date_joined
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, username, email, first_name, last_name
                    """, (
                        user_data['username'],
                        user_data['email'],
                        hashed_password,
                        user_data.get('first_name', ''),
                        user_data.get('last_name', ''),
                        True,
                        False,
                        False,
                        datetime.utcnow()
                    ))
                   
                    row = cursor.fetchone()
                    conn.commit()
                   
                    return {
                        "id": row["id"],
                        "username": row["username"],
                        "email": row["email"],
                        "first_name": row["first_name"],
                        "last_name": row["last_name"]
                    }
                   
            except ValueError:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                logger.error(f"Error in register_user: {e}")
                raise
   
    def login_user(self, user_data):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if user_data.get('email'):
                        cursor.execute("""
                            SELECT id, username, first_name, last_name, email, password
                            FROM auth_user
                            WHERE email = %s AND is_active = TRUE
                            LIMIT 1
                        """, (user_data['email'],))
                    else:
                        cursor.execute("""
                            SELECT id, username, first_name, last_name, email, password
                            FROM auth_user
                            WHERE username = %s AND is_active = TRUE
                            LIMIT 1
                        """, (user_data['username'],))
                   
                    result = cursor.fetchone()
                   
                    if not result:
                        raise ValueError("Invalid credentials")
                   
                    if not self.verify_django_password(user_data['password'], result['password']):
                        raise ValueError("Invalid credentials")
                   
                    cursor.execute("""
                        UPDATE auth_user
                        SET last_login = %s
                        WHERE id = %s
                    """, (datetime.utcnow(), result['id']))
                    
                    conn.commit()
                   
                    return {
                        "id": result['id'],
                        "username": result['username'],
                        "email": result['email'],
                        "first_name": result.get('first_name', ''),
                        "last_name": result.get('last_name', '')
                    }
                   
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"Error during login: {e}")
                raise
   
    def get_user_by_id(self, user_id: int):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, username, first_name, last_name, email
                    FROM auth_user
                    WHERE id = %s AND is_active = TRUE
                """, (user_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "id": row['id'],
                        "username": row['username'],
                        "email": row['email'],
                        "first_name": row.get('first_name', ''),
                        "last_name": row.get('last_name', '')
                    }
                return None
    
    def get_user_by_username(self, username: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, username, first_name, last_name, email
                    FROM auth_user
                    WHERE username = %s AND is_active = TRUE
                """, (username.lower(),))
                row = cursor.fetchone()
                if row:
                    return {
                        "id": row['id'],
                        "username": row['username'],
                        "email": row['email'],
                        "first_name": row.get('first_name', ''),
                        "last_name": row.get('last_name', '')
                    }
                return None
    
    
    def blacklist_token(self, token: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO token_blacklist (token, blacklisted_at)
                        VALUES (%s, %s)
                        ON CONFLICT (token) DO NOTHING
                    """, (token, datetime.utcnow()))
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Error blacklisting token: {e}")
                raise
    
    def is_token_blacklisted(self, token: str) -> bool:
        with self.get_connection_context() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 1 FROM token_blacklist WHERE token = %s
                """, (token,))
                return cursor.fetchone() is not None
   
    def save_weather_data(self, weather_data):
        """Save weather data with batch_id to group forecast points from same API call"""
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    obs_id = str(uuid.uuid4())
                    batch_id = weather_data.get('batch_id')  # All forecasts from same request share this
                   
                    cursor.execute("""
                        INSERT INTO weather_observations
                        (obs_id, obs_time, lat, lon, temperature, humidity, thi, raw, 
                         batch_id, is_forecast, barn_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING obs_id, obs_time, batch_id
                    """, (
                        obs_id,
                        weather_data.get('obs_time'),
                        weather_data.get('lat'),
                        weather_data.get('lon'),
                        weather_data.get('temperature'),
                        weather_data.get('humidity'),
                        weather_data.get('thi'),
                        json.dumps(weather_data.get('raw', {})),
                        batch_id,
                        weather_data.get('is_forecast', False),
                        weather_data.get('barn_id')
                    ))
                   
                    result = cursor.fetchone()
                    conn.commit()
                   
                    return result
                   
            except Exception as e:
                conn.rollback()
                logger.error(f"Error saving weather data: {e}")
                raise
    
    def get_app_settings(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT key, value FROM app_settings")
                rows = cursor.fetchall()
                return {row["key"]: row["value"] for row in rows}

    def set_app_setting(self, key: str, value: str):
        with self.get_connection_context() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE 
                    SET value = EXCLUDED.value, updated_at = NOW()
                """, (key, value))
                conn.commit()
                return {"key": key, "value": value}

    def get_all_barns(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id as barn_id, identifier as name, latitude, longitude
                    FROM farm_management_farmparcel
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    AND deleted_at IS NULL AND parcel_type = 'barn'
                """)
                return cursor.fetchall()
    
    
    

    def get_all_farms(self):
        """Return all farms from the Farm Calendar (the central system of record).

        Single deployment = one organisation, so every non-deleted
        farm_management_farm row belongs to this deployment. Farms are
        created/managed in Farm Calendar; Inokron only reads them.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        f.id as farm_id,
                        f.name as name,
                        mfm.moohero_farm_id as moohero_id,
                        COUNT(DISTINCT b.id) as barn_count
                    FROM farm_management_farm f
                    LEFT JOIN farm_management_farmparcel b
                        ON f.id = b.farm_id
                        AND b.deleted_at IS NULL
                        AND b.parcel_type = 'barn'
                    LEFT JOIN moohero_farm_mapping mfm
                        ON mfm.farm_id = f.id
                    WHERE f.deleted_at IS NULL
                    GROUP BY f.id, f.name, mfm.moohero_farm_id
                    ORDER BY f.name
                """)
                return cursor.fetchall()

    def get_farm_by_id(self, farm_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        f.id as farm_id,
                        f.name as name,
                        COUNT(DISTINCT b.id) as barn_count
                    FROM farm_management_farm f
                    LEFT JOIN farm_management_farmparcel b
                        ON f.id = b.farm_id
                        AND b.deleted_at IS NULL
                        AND b.parcel_type = 'barn'
                    WHERE f.id = %s AND f.deleted_at IS NULL
                    GROUP BY f.id, f.name
                """, (farm_id,))
                return cursor.fetchone()
    
    def get_barns_by_farm_id(self, farm_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        b.id as barn_id,
                        b.identifier as barn_name,
                        b.latitude,
                        b.longitude,
                        b.farm_id,
                        COUNT(DISTINCT fl.feeding_location_id) as feeding_location_count
                    FROM farm_management_farmparcel b
                    LEFT JOIN feeding_locations fl ON b.id = fl.barn_id
                    WHERE b.farm_id = %s AND b.deleted_at IS NULL AND b.parcel_type = 'barn'
                    GROUP BY b.id, b.identifier, b.latitude, b.longitude, b.farm_id
                    ORDER BY b.identifier
                """, (farm_id,))
                return cursor.fetchall()
    
    def get_barn_by_id(self, barn_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        b.id as barn_id,
                        b.identifier as barn_name,
                        b.latitude,
                        b.longitude,
                        b.farm_id,
                        COUNT(DISTINCT fl.feeding_location_id) as feeding_location_count
                    FROM farm_management_farmparcel b
                    LEFT JOIN feeding_locations fl ON b.id = fl.barn_id
                    WHERE b.id = %s AND b.deleted_at IS NULL AND b.parcel_type = 'barn'
                    GROUP BY b.id, b.identifier, b.latitude, b.longitude, b.farm_id
                """, (barn_id,))
                return cursor.fetchone()
    
    def get_feeding_location_by_id(self, feeding_location_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations' AND column_name = 'is_hidden'
                    LIMIT 1
                    """
                )
                has_is_hidden = cursor.fetchone() is not None

                hidden_select_expr = "is_hidden" if has_is_hidden else "FALSE::boolean as is_hidden"
                cursor.execute(f"""
                    SELECT feeding_location_id, barn_id, name, external_id, {hidden_select_expr}
                    FROM feeding_locations
                    WHERE feeding_location_id = %s
                """, (feeding_location_id,))
                return cursor.fetchone()
    
    def update_feeding_location(
        self,
        feeding_location_id: str,
        name: str = None,
        is_hidden: bool = None
    ):
        """Update a feeding location"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations' AND column_name = 'is_hidden'
                    LIMIT 1
                    """
                )
                has_is_hidden = cursor.fetchone() is not None

                # Build dynamic update query
                updates = []
                params = []
                
                if name is not None:
                    updates.append("name = %s")
                    params.append(name)

                if is_hidden is not None and has_is_hidden:
                    updates.append("is_hidden = %s")
                    params.append(is_hidden)
                
                if not updates:
                    # Nothing to update
                    return self.get_feeding_location_by_id(feeding_location_id)
                
                params.append(feeding_location_id)
                
                query = f"""
                    UPDATE feeding_locations
                    SET {', '.join(updates)}
                    WHERE feeding_location_id = %s
                    RETURNING feeding_location_id, barn_id, name, external_id
                """
                
                cursor.execute(query, params)
                result = cursor.fetchone()
                conn.commit()
                if not result:
                    return None
                return self.get_feeding_location_by_id(feeding_location_id)
    
    def delete_feeding_location(self, feeding_location_id: str):
        """Hard-delete a feeding location.

        Refuses if the location has telemetry history (preserve the data -
        callers should hide it instead). For empty locations, clears the
        remaining NO ACTION references first so the delete always succeeds.
        Raises ValueError if telemetry exists.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT 1 FROM telemetry_readings WHERE feeding_location_id = %s LIMIT 1",
                    (feeding_location_id,),
                )
                if cursor.fetchone():
                    raise ValueError(
                        "This feeding location has telemetry history; hide it instead of deleting."
                    )

                # Clear the remaining NO ACTION references (cascades handle the rest).
                cursor.execute(
                    "DELETE FROM feeding_location_settings WHERE feeding_location_id = %s",
                    (feeding_location_id,),
                )
                cursor.execute(
                    "DELETE FROM calendar_event_links WHERE feeding_location_id = %s",
                    (feeding_location_id,),
                )
                cursor.execute(
                    "UPDATE devices SET feeding_location_id = NULL WHERE feeding_location_id = %s",
                    (feeding_location_id,),
                )
                cursor.execute(
                    "DELETE FROM feeding_locations WHERE feeding_location_id = %s",
                    (feeding_location_id,),
                )
                conn.commit()
                return True


    def list_devices_with_mapping(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'devices' AND column_name = 'barn_id'
                    LIMIT 1
                    """
                )
                has_device_barn = cursor.fetchone() is not None

                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations' AND column_name = 'external_id'
                    LIMIT 1
                    """
                )
                has_external_id = cursor.fetchone() is not None

                mapped_barn_expr = "COALESCE(d.barn_id, fl.barn_id)" if has_device_barn else "fl.barn_id"
                join_barn_expr = "COALESCE(d.barn_id, fl.barn_id)" if has_device_barn else "fl.barn_id"
                external_id_expr = "fl.external_id" if has_external_id else "NULL::text"

                cursor.execute(
                    f"""
                    SELECT
                        d.device_id,
                        d.device_eui,
                        d.display_name,
                        {mapped_barn_expr} as barn_id,
                        b.identifier as barn_name,
                        d.feeding_location_id,
                        fl.name as feeding_location_name,
                        {external_id_expr} as feeding_location_external_id
                    FROM devices d
                    LEFT JOIN feeding_locations fl
                        ON d.feeding_location_id = fl.feeding_location_id
                    LEFT JOIN farm_management_farmparcel b
                        ON {join_barn_expr} = b.id
                    ORDER BY d.device_eui
                    """
                )
                return cursor.fetchall()

    def set_device_barn(
        self,
        device_eui: str,
        barn_id: str,
        display_name: str = None
    ):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'devices' AND column_name = 'barn_id'
                        LIMIT 1
                        """
                    )
                    has_device_barn = cursor.fetchone() is not None

                    cursor.execute(
                        """
                        SELECT id, identifier
                        FROM farm_management_farmparcel
                        WHERE id = %s
                          AND deleted_at IS NULL
                          AND parcel_type = 'barn'
                        LIMIT 1
                        """,
                        (barn_id,)
                    )
                    barn = cursor.fetchone()
                    if not barn:
                        raise ValueError("Barn not found")

                    cursor.execute(
                        """
                        SELECT device_id, barn_id, feeding_location_id, display_name
                        FROM devices
                        WHERE device_eui = %s
                        LIMIT 1
                        """,
                        (device_eui,)
                    )
                    device = cursor.fetchone()

                    if not device:
                        device_id = str(uuid.uuid4())
                        if has_device_barn:
                            cursor.execute(
                                """
                                INSERT INTO devices (device_id, device_eui, barn_id, display_name)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (device_id, device_eui, barn_id, display_name)
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO devices (device_id, device_eui, display_name)
                                VALUES (%s, %s, %s)
                                """,
                                (device_id, device_eui, display_name)
                            )
                    else:
                        device_id = device["device_id"]
                        new_name = display_name or device.get("display_name")
                        if has_device_barn:
                            cursor.execute(
                                """
                                UPDATE devices
                                SET barn_id = %s,
                                    display_name = %s
                                WHERE device_id = %s
                                """,
                                (barn_id, new_name, device_id)
                            )
                        else:
                            cursor.execute(
                                """
                                UPDATE devices
                                SET display_name = %s
                                WHERE device_id = %s
                                """,
                                (new_name, device_id)
                            )

                    conn.commit()
                    return {
                        "device_id": device_id,
                        "device_eui": device_eui,
                        "barn_id": barn_id,
                        "barn_name": barn.get("identifier"),
                        "barn_mapping_persisted": has_device_barn,
                        "display_name": display_name or (device.get("display_name") if device else None)
                    }
            except Exception as e:
                conn.rollback()
                logger.error(f"Error linking device to barn: {e}")
                raise

    def set_device_feeding_location(
        self,
        device_eui: str,
        feeding_location_id: str,
        display_name: str = None
    ):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'devices' AND column_name = 'barn_id'
                        LIMIT 1
                        """
                    )
                    has_device_barn = cursor.fetchone() is not None

                    cursor.execute(
                        """
                        SELECT feeding_location_id, barn_id
                        FROM feeding_locations
                        WHERE feeding_location_id = %s
                        """,
                        (feeding_location_id,)
                    )
                    location = cursor.fetchone()
                    if not location:
                        raise ValueError("Feeding location not found")

                    cursor.execute(
                        """
                        SELECT device_id, barn_id, feeding_location_id, display_name
                        FROM devices
                        WHERE device_eui = %s
                        LIMIT 1
                        """,
                        (device_eui,)
                    )
                    device = cursor.fetchone()

                    if not device:
                        device_id = str(uuid.uuid4())
                        if has_device_barn:
                            cursor.execute(
                                """
                                INSERT INTO devices (device_id, device_eui, barn_id, feeding_location_id, display_name)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (
                                    device_id,
                                    device_eui,
                                    location["barn_id"],
                                    feeding_location_id,
                                    display_name
                                )
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO devices (device_id, device_eui, feeding_location_id, display_name)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (
                                    device_id,
                                    device_eui,
                                    feeding_location_id,
                                    display_name
                                )
                            )
                    else:
                        device_id = device["device_id"]
                        new_name = display_name or device.get("display_name")
                        if has_device_barn:
                            cursor.execute(
                                """
                                UPDATE devices
                                SET barn_id = %s,
                                    feeding_location_id = %s,
                                    display_name = %s
                                WHERE device_id = %s
                                """,
                                (location["barn_id"], feeding_location_id, new_name, device_id)
                            )
                        else:
                            cursor.execute(
                                """
                                UPDATE devices
                                SET feeding_location_id = %s,
                                    display_name = %s
                                WHERE device_id = %s
                                """,
                                (feeding_location_id, new_name, device_id)
                            )
                    conn.commit()

                    return {
                        "device_id": device_id,
                        "device_eui": device_eui,
                        "feeding_location_id": feeding_location_id,
                        "barn_id": location["barn_id"],
                        "display_name": display_name or (device.get("display_name") if device else None)
                    }
            except Exception as e:
                conn.rollback()
                logger.error(f"Error linking device to feeding location: {e}")
                raise

    def upsert_device_location_mapping(
        self,
        device_eui: str,
        barn_id: str,
        source_location_key: str,
        feeding_location_id: str,
    ):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT to_regclass('public.device_feeding_location_mappings') AS table_name")
                    if not cursor.fetchone().get("table_name"):
                        logger.warning(
                            "device_feeding_location_mappings missing; creating compatibility table"
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS device_feeding_location_mappings (
                                mapping_id uuid PRIMARY KEY,
                                device_id uuid NOT NULL,
                                barn_id uuid NOT NULL,
                                source_location_key text NOT NULL,
                                feeding_location_id uuid NOT NULL,
                                created_at timestamp without time zone NOT NULL DEFAULT NOW(),
                                updated_at timestamp without time zone NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_device_location_source
                            ON device_feeding_location_mappings (device_id, source_location_key)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS ix_device_location_barn
                            ON device_feeding_location_mappings (barn_id)
                            """
                        )

                    normalized_key = (source_location_key or "").strip().lower()
                    if not normalized_key:
                        raise ValueError("source_location_key is required")

                    cursor.execute(
                        """
                        SELECT device_id
                        FROM devices
                        WHERE device_eui = %s
                        LIMIT 1
                        """,
                        (device_eui,)
                    )
                    device = cursor.fetchone()
                    if not device:
                        raise ValueError("Device not found. Link device to a barn first")

                    cursor.execute(
                        """
                        SELECT feeding_location_id, barn_id, name, external_id
                        FROM feeding_locations
                        WHERE feeding_location_id = %s
                        LIMIT 1
                        """,
                        (feeding_location_id,)
                    )
                    location = cursor.fetchone()
                    if not location:
                        raise ValueError("Feeding location not found")
                    if str(location["barn_id"]) != str(barn_id):
                        raise ValueError("Feeding location does not belong to provided barn")

                    cursor.execute(
                        """
                        INSERT INTO device_feeding_location_mappings (
                            mapping_id,
                            device_id,
                            barn_id,
                            source_location_key,
                            feeding_location_id,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT (device_id, source_location_key)
                        DO UPDATE SET
                            barn_id = EXCLUDED.barn_id,
                            feeding_location_id = EXCLUDED.feeding_location_id,
                            updated_at = NOW()
                        RETURNING mapping_id, device_id, barn_id, source_location_key, feeding_location_id, updated_at
                        """,
                        (
                            str(uuid.uuid4()),
                            device["device_id"],
                            barn_id,
                            normalized_key,
                            feeding_location_id,
                        )
                    )
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error upserting device location mapping: {e}")
                raise

    def list_device_location_mappings(self, device_eui: str = None, barn_id: str = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT to_regclass('public.device_feeding_location_mappings') AS table_name")
                if not cursor.fetchone().get("table_name"):
                    logger.warning(
                        "device_feeding_location_mappings table not found; returning empty mapping list"
                    )
                    return []

                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations' AND column_name = 'external_id'
                    LIMIT 1
                    """
                )
                has_external_id = cursor.fetchone() is not None
                external_id_expr = "fl.external_id" if has_external_id else "NULL::text"

                query = """
                    SELECT
                        m.mapping_id,
                        d.device_eui,
                        m.barn_id,
                        b.identifier as barn_name,
                        m.source_location_key,
                        m.feeding_location_id,
                        fl.name as feeding_location_name,
                        {external_id_expr} as feeding_location_external_id,
                        m.updated_at
                    FROM device_feeding_location_mappings m
                    INNER JOIN devices d ON d.device_id = m.device_id
                    LEFT JOIN farm_management_farmparcel b ON b.id = m.barn_id
                    LEFT JOIN feeding_locations fl ON fl.feeding_location_id = m.feeding_location_id
                """.format(external_id_expr=external_id_expr)
                clauses = []
                params = []
                if device_eui:
                    clauses.append("d.device_eui = %s")
                    params.append(device_eui)
                if barn_id:
                    clauses.append("m.barn_id = %s")
                    params.append(barn_id)
                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                query += " ORDER BY d.device_eui, m.source_location_key"
                cursor.execute(query, tuple(params))
                return cursor.fetchall()

    def upsert_device_barn_mapping(
        self,
        device_eui: str,
        source_barn_key: str,
        barn_id: str,
    ):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT to_regclass('public.device_barn_mappings') AS table_name")
                    if not cursor.fetchone().get("table_name"):
                        logger.warning(
                            "device_barn_mappings missing; creating compatibility table"
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS device_barn_mappings (
                                mapping_id uuid PRIMARY KEY,
                                device_id uuid NOT NULL,
                                source_barn_key text NOT NULL,
                                barn_id uuid NOT NULL,
                                created_at timestamp without time zone NOT NULL DEFAULT NOW(),
                                updated_at timestamp without time zone NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_device_barn_source
                            ON device_barn_mappings (device_id, source_barn_key)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS ix_device_barn_id
                            ON device_barn_mappings (barn_id)
                            """
                        )

                    normalized_key = (source_barn_key or "").strip().lower()
                    if not normalized_key:
                        raise ValueError("source_barn_key is required")

                    cursor.execute(
                        """
                        SELECT device_id
                        FROM devices
                        WHERE device_eui = %s
                        LIMIT 1
                        """,
                        (device_eui,)
                    )
                    device = cursor.fetchone()
                    if not device:
                        raise ValueError("Device not found. Link device to a barn first")

                    cursor.execute(
                        """
                        SELECT id, identifier
                        FROM farm_management_farmparcel
                        WHERE id = %s
                          AND deleted_at IS NULL
                          AND parcel_type = 'barn'
                        LIMIT 1
                        """,
                        (barn_id,)
                    )
                    barn = cursor.fetchone()
                    if not barn:
                        raise ValueError("Barn not found")

                    cursor.execute(
                        """
                        INSERT INTO device_barn_mappings (
                            mapping_id,
                            device_id,
                            source_barn_key,
                            barn_id,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT (device_id, source_barn_key)
                        DO UPDATE SET
                            barn_id = EXCLUDED.barn_id,
                            updated_at = NOW()
                        RETURNING mapping_id, device_id, source_barn_key, barn_id, updated_at
                        """,
                        (
                            str(uuid.uuid4()),
                            device["device_id"],
                            normalized_key,
                            barn_id,
                        )
                    )
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error upserting device barn mapping: {e}")
                raise

    def list_device_barn_mappings(self, device_eui: str = None, barn_id: str = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT to_regclass('public.device_barn_mappings') AS table_name")
                if not cursor.fetchone().get("table_name"):
                    logger.warning(
                        "device_barn_mappings table not found; returning empty mapping list"
                    )
                    return []

                query = """
                    SELECT
                        m.mapping_id,
                        d.device_eui,
                        m.source_barn_key,
                        m.barn_id,
                        b.identifier as barn_name,
                        m.updated_at
                    FROM device_barn_mappings m
                    INNER JOIN devices d ON d.device_id = m.device_id
                    LEFT JOIN farm_management_farmparcel b ON b.id = m.barn_id
                """
                clauses = []
                params = []
                if device_eui:
                    clauses.append("d.device_eui = %s")
                    params.append(device_eui)
                if barn_id:
                    clauses.append("m.barn_id = %s")
                    params.append(barn_id)
                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                query += " ORDER BY d.device_eui, m.source_barn_key"
                cursor.execute(query, tuple(params))
                return cursor.fetchall()

    def list_incoming_location_names(
        self,
        device_eui: str = None,
        barn_id: str = None,
        hours: int = 168,
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                incoming_key_expr = """
                    COALESCE(
                        NULLIF(BTRIM((tr.raw::jsonb ->> 'feeding_location_id')), ''),
                        NULLIF(BTRIM((tr.raw::jsonb ->> 'source_location_key')), '')
                    )
                """

                query = f"""
                    SELECT
                        {incoming_key_expr} AS incoming_feeding_location_name,
                        COUNT(*)::int AS seen_count,
                        MIN(tr.time) AS first_seen,
                        MAX(tr.time) AS last_seen
                    FROM telemetry_readings tr
                    WHERE tr.time >= NOW() - (%s * INTERVAL '1 hour')
                      AND {incoming_key_expr} IS NOT NULL
                """
                params = [hours]

                if device_eui:
                    query += " AND tr.device_eui = %s"
                    params.append(device_eui)

                if barn_id:
                    query += " AND tr.barn_id = %s"
                    params.append(barn_id)

                query += f"""
                    GROUP BY {incoming_key_expr}
                    ORDER BY last_seen DESC
                """

                cursor.execute(query, tuple(params))
                return cursor.fetchall()

    def list_incoming_barn_names(
        self,
        device_eui: str = None,
        hours: int = 168,
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                incoming_key_expr = """
                    COALESCE(
                        NULLIF(BTRIM((tr.raw::jsonb ->> 'barn_id')), ''),
                        NULLIF(BTRIM((tr.raw::jsonb ->> 'barnId')), '')
                    )
                """

                query = f"""
                    SELECT
                        {incoming_key_expr} AS incoming_barn_name,
                        COUNT(*)::int AS seen_count,
                        MIN(tr.time) AS first_seen,
                        MAX(tr.time) AS last_seen
                    FROM telemetry_readings tr
                    WHERE tr.time >= NOW() - (%s * INTERVAL '1 hour')
                      AND {incoming_key_expr} IS NOT NULL
                """
                params = [hours]

                if device_eui:
                    query += " AND tr.device_eui = %s"
                    params.append(device_eui)

                query += f"""
                    GROUP BY {incoming_key_expr}
                    ORDER BY last_seen DESC
                """

                cursor.execute(query, tuple(params))
                return cursor.fetchall()
    
    def get_feeding_location_history(self, feeding_location_id: str, hours: int = 24, start_time=None, end_time=None):
        """Get historical telemetry readings for a feeding location"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT 
                        q.time AT TIME ZONE 'Europe/Ljubljana' AT TIME ZONE 'UTC' AS time,
                        q.device_eui,
                        q.device_id,
                        q.barn_id,
                        q.reading_kind,
                        q.numeric_value,
                        q.temperature,
                        q.humidity,
                        CASE
                            WHEN q.temperature IS NOT NULL AND q.humidity IS NOT NULL THEN ROUND(
                                (
                                    ((q.temperature * 9.0 / 5.0) + 32.0)
                                    - (0.55 - (0.0055 * q.humidity)) * (((q.temperature * 9.0 / 5.0) + 32.0) - 58.0)
                                )::numeric,
                                2
                            )
                            ELSE NULL
                        END AS thi,
                        q.raw
                    FROM (
                        SELECT
                            tr.time,
                            tr.device_eui,
                            tr.device_id,
                            tr.barn_id,
                            tr.reading_kind,
                            tr.numeric_value,
                            CASE
                                WHEN tr.reading_kind = 'feed_level_percentage' THEN COALESCE(tr.temperature, climate_match.temperature)
                                ELSE tr.temperature
                            END AS temperature,
                            CASE
                                WHEN tr.reading_kind = 'feed_level_percentage' THEN COALESCE(tr.humidity, climate_match.humidity)
                                ELSE tr.humidity
                            END AS humidity,
                            tr.raw
                        FROM telemetry_readings tr
                        LEFT JOIN feeding_locations fl
                            ON fl.feeding_location_id::text = tr.feeding_location_id::text
                        LEFT JOIN LATERAL (
                            SELECT c.temperature, c.humidity
                            FROM telemetry_readings c
                            WHERE c.reading_kind = 'climate'
                                AND c.barn_id::text = COALESCE(tr.barn_id::text, fl.barn_id::text)
                                AND c.time BETWEEN tr.time - INTERVAL '30 minutes' AND tr.time + INTERVAL '30 minutes'
                            ORDER BY ABS(EXTRACT(EPOCH FROM (c.time - tr.time)))
                            LIMIT 1
                        ) AS climate_match
                            ON tr.reading_kind = 'feed_level_percentage'
                        WHERE tr.feeding_location_id = %s
                """
                params = [feeding_location_id]
                if start_time:
                    query += " AND tr.time >= %s"
                    params.append(start_time)
                else:
                    query += " AND tr.time >= NOW() - (%s * INTERVAL '1 hour')"
                    params.append(hours)
                
                if end_time:
                    query += " AND tr.time <= %s"
                    params.append(end_time)

                query += """
                    ) AS q
                    ORDER BY q.time DESC
                """
                cursor.execute(query, tuple(params))
                return cursor.fetchall()

    def get_farm_calendar_feeding_events_for_feeding_location(
        self,
        feeding_location_id: str,
        barn_id: str = None,
        hours: int = 24,
        limit: int = 500,
        start_time = None,
        end_time = None,
    ):
        """
        Return Farm Calendar 'Feeding' activities for a feeding-location parcel_id within the last N hours.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM farm_activities_farmcalendaractivitytype WHERE name = 'Feeding'"
                )
                feeding_type = cursor.fetchone()

                if not feeding_type:
                    return []

                query = """
                    SELECT
                        a.id AS activity_id,
                        a.title,
                        a.start_datetime,
                        a.end_datetime,
                        a.details,
                        a.parcel_id,
                        a.parent_activity_id
                    FROM farm_activities_farmcalendaractivity a
                    WHERE a.activity_type_id = %s
                      AND (
                        a.parcel_id = %s
                        OR (%s IS NOT NULL AND a.parcel_id = %s)
                      )
                """
                params = [feeding_type["id"], feeding_location_id, barn_id, barn_id]
                
                if start_time:
                    query += " AND a.start_datetime >= %s"
                    params.append(start_time)
                else:
                    query += " AND a.start_datetime >= NOW() - (%s * INTERVAL '1 hour')"
                    params.append(hours)
                
                if end_time:
                    query += " AND a.start_datetime <= %s"
                    params.append(end_time)
                
                query += """
                    ORDER BY a.start_datetime ASC
                    LIMIT %s
                """
                params.append(limit)
                
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()

                if not rows:
                    return []

                events = []
                for r in rows:
                    dt = r.get("start_datetime")
                    events.append(
                        {
                            "feeding_location_id": str(r.get("parcel_id")) if r.get("parcel_id") is not None else None,
                            "feeding_activity_id": str(r.get("activity_id")) if r.get("activity_id") is not None else None,
                            "timestamp": dt.isoformat() if dt else None,
                            "title": r.get("title"),
                            "details": r.get("details"),
                            "end_datetime": r.get("end_datetime").isoformat() if r.get("end_datetime") else None,
                            "parent_activity_id": str(r.get("parent_activity_id")) if r.get("parent_activity_id") else None,
                        }
                    )

                return events

    def get_feeding_events_from_schedules(
        self,
        feeding_location_id: str,
        barn_id: str = None,
        hours: int = 24,
        limit: int = 500,
    ):
        """
        Fallback for graph points when Farm Calendar DB isn't available in this backend DB.

        Uses local `feeding_schedules.actual_feed_datetime` (which is populated by calendar sync
        and one-time feeding creation).
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        fs.id AS schedule_id,
                        fs.barn_id,
                        fs.feeding_location_id,
                        fs.schedule_name,
                        fs.notes,
                        fs.actual_feed_datetime,
                        fs.farm_calendar_activity_id
                    FROM feeding_schedules fs
                    WHERE fs.actual_feed_datetime IS NOT NULL
                      AND fs.actual_feed_datetime >= NOW() - (%s * INTERVAL '1 hour')
                      AND (
                        fs.feeding_location_id = %s
                        OR (%s IS NOT NULL AND fs.barn_id = %s)
                      )
                    ORDER BY fs.actual_feed_datetime ASC
                    LIMIT %s
                    """,
                    (hours, feeding_location_id, barn_id, barn_id, limit),
                )
                rows = cursor.fetchall() or []

                events = []
                for r in rows:
                    dt = r.get("actual_feed_datetime")
                    events.append(
                        {
                            "feeding_location_id": str(r.get("feeding_location_id")) if r.get("feeding_location_id") else None,
                            "barn_id": str(r.get("barn_id")) if r.get("barn_id") else None,
                            "feeding_activity_id": str(r.get("farm_calendar_activity_id") or r.get("schedule_id")),
                            "timestamp": dt.isoformat() if dt else None,
                            "title": r.get("schedule_name"),
                            "details": r.get("notes"),
                            "source": "feeding_schedules",
                        }
                    )
                return events
    
    def insert_weather_forecast(self, barn_id: str, batch_id: str, forecast_time, forecast_for, temperature: float, humidity: float, thi: float, raw: dict):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                try:
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'weather_forecasts'
                          AND column_name IN (
                              'barn_id', 'batch_id', 'forecast_time', 'forecast_for',
                              'temperature', 'humidity', 'thi', 'raw'
                          )
                        """
                    )
                    columns = {row["column_name"] for row in cursor.fetchall()}

                    insert_cols = []
                    values = []
                    placeholders = []

                    def add_col(name, value):
                        if name in columns:
                            insert_cols.append(name)
                            values.append(value)
                            placeholders.append("%s")

                    add_col("barn_id", barn_id)
                    add_col("batch_id", batch_id)
                    add_col("forecast_time", forecast_time)
                    add_col("forecast_for", forecast_for)
                    add_col("temperature", temperature)
                    add_col("humidity", humidity)
                    add_col("thi", thi)
                    add_col("raw", raw)

                    if not insert_cols:
                        raise ValueError("weather_forecasts has no supported insert columns")

                    cursor.execute(
                        f"""
                        INSERT INTO weather_forecasts ({', '.join(insert_cols)})
                        VALUES ({', '.join(placeholders)})
                        RETURNING *
                        """,
                        tuple(values)
                    )
                    result = cursor.fetchone()
                    conn.commit()
                    return result
                except Exception:
                    conn.rollback()
                    logger.exception(
                        "insert_weather_forecast failed",
                        extra={"barn_id": barn_id, "batch_id": batch_id}
                    )
                    raise
    
    def get_weather_forecast(self, barn_id: str, hours: int = 48):
        """Get weather forecast for a barn for the next X hours"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                try:
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'weather_forecasts'
                          AND column_name IN (
                              'forecast_for',
                              'forecast_time',
                              'temperature',
                              'humidity',
                              'thi',
                              'barn_id'
                          )
                        """
                    )
                    columns = {row["column_name"] for row in cursor.fetchall()}

                    if "forecast_for" in columns:
                        time_column = "forecast_for"
                    elif "forecast_time" in columns:
                        time_column = "forecast_time"
                    else:
                        logger.error("weather_forecasts has neither forecast_for nor forecast_time")
                        return []

                    temperature_expr = "temperature" if "temperature" in columns else "NULL::double precision"
                    humidity_expr = "humidity" if "humidity" in columns else "NULL::double precision"
                    thi_expr = "thi" if "thi" in columns else "NULL::double precision"
                    forecast_time_expr = "forecast_time" if "forecast_time" in columns else f"{time_column}"

                    if "barn_id" in columns:
                        where_clauses = [
                            "barn_id::text = %s",
                            f"{time_column} >= NOW()",
                            f"{time_column} <= NOW() + (%s * INTERVAL '1 hour')"
                        ]
                        params = [barn_id, hours]
                    else:
                        logger.warning(
                            "weather_forecasts missing barn_id; returning empty forecast to avoid wrong-barn data",
                            extra={"barn_id": barn_id}
                        )
                        return []

                    where_sql = " AND ".join(where_clauses)

                    cursor.execute(
                        f"""
                        SELECT
                            {time_column} as forecast_for,
                            {temperature_expr} as temperature,
                            {humidity_expr} as humidity,
                            {thi_expr} as thi,
                            {forecast_time_expr} as forecast_time
                        FROM weather_forecasts
                        WHERE {where_sql}
                        ORDER BY {time_column}
                        LIMIT %s
                        """,
                        (*params, hours)
                    )
                    return cursor.fetchall()
                except Exception:
                    logger.exception(
                        "DB get_weather_forecast failed",
                        extra={"barn_id": barn_id, "hours": hours}
                    )
                    raise
    
    def get_current_weather_with_thi(self, barn_id: str):
        """Get most recent weather observation for a barn"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        wo.obs_id,
                        wo.obs_time,
                        wo.temperature,
                        wo.humidity,
                        wo.thi,
                        b.id as barn_id,
                        b.latitude,
                        b.longitude
                    FROM weather_observations wo
                    JOIN farm_management_farmparcel b ON wo.barn_id = b.id
                    WHERE b.id = %s
                    ORDER BY wo.obs_time DESC
                    LIMIT 1
                """, (barn_id,))
                return cursor.fetchone()

    def get_all_feeding_locations_with_barns(self):
        """Get all feeding locations with their associated barns"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        fl.feeding_location_id,
                        fl.name as location_name,
                        fl.external_id,
                        fl.barn_id,
                        b.id as barn_id,
                        b.identifier as barn_name
                    FROM feeding_locations fl
                    LEFT JOIN farm_management_farmparcel b ON fl.barn_id = b.id
                    WHERE fl.is_hidden = FALSE
                    ORDER BY fl.name, b.identifier
                """)
                return cursor.fetchall()        
    
    def get_feeding_locations_by_barn(self, barn_id: str, include_hidden: bool = False):
        """Get all feeding locations for a specific barn"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations' AND column_name = 'is_hidden'
                    LIMIT 1
                    """
                )
                has_is_hidden = cursor.fetchone() is not None

                hidden_select_expr = "fl.is_hidden" if has_is_hidden else "FALSE"

                query = f"""
                    SELECT
                        fl.feeding_location_id,
                        fl.external_id,
                        fl.barn_id,
                        fl.name,
                        {hidden_select_expr} as is_hidden,
                        EXISTS (
                            SELECT 1 FROM telemetry_readings tr
                            WHERE tr.feeding_location_id = fl.feeding_location_id
                        ) as has_telemetry,
                        fls.low_feed_threshold
                    FROM feeding_locations fl
                    LEFT JOIN feeding_location_settings fls
                        ON fl.feeding_location_id = fls.feeding_location_id
                    WHERE fl.barn_id = %s
                """
                params = [barn_id]
                if has_is_hidden and not include_hidden:
                    query += " AND fl.is_hidden = FALSE"
                query += " ORDER BY fl.name"

                cursor.execute(query, tuple(params))
                return cursor.fetchall()
    

    def get_feed_level_history_for_location(self, feeding_location_id: str, minutes: int):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT time, numeric_value, temperature
                    FROM telemetry_readings
                    WHERE feeding_location_id = %s
                        AND reading_kind = 'feed_level_percentage'
                        AND time >= NOW() - INTERVAL '%s minutes'
                    ORDER BY time ASC
                    """,
                    (feeding_location_id, minutes)
                )
                return cursor.fetchall()

    def get_feed_level_window(
        self,
        feeding_location_id: str,
        start_time,
        end_time
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT time, numeric_value
                    FROM telemetry_readings
                    WHERE feeding_location_id = %s
                        AND reading_kind = 'feed_level_percentage'
                        AND time >= %s
                        AND time <= %s
                    ORDER BY time ASC
                    """,
                    (feeding_location_id, start_time, end_time)
                )
                return cursor.fetchall()
    

    def get_latest_feed_levels(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT DISTINCT ON (fl.feeding_location_id)
                        tr.time,
                        tr.device_eui,
                        tr.barn_id,
                        fl.feeding_location_id,
                        fl.name as location_name,
                        fl.external_id,
                        tr.numeric_value as feed_level,
                        b.identifier as barn_name,
                        -- Resolved low-feed alert threshold (low_feed_percent):
                        -- location override -> global override -> system default (20).
                        -- Mirrors get_threshold_value() / THRESHOLD_DEFAULTS.
                        COALESCE(
                            (loc_thr.value #>> '{}')::numeric,
                            (glob_thr.value #>> '{}')::numeric,
                            20
                        ) as low_feed_threshold
                    FROM telemetry_readings tr
                    INNER JOIN feeding_locations fl
                        ON tr.feeding_location_id::text = fl.feeding_location_id::text
                    LEFT JOIN farm_management_farmparcel b
                        ON COALESCE(tr.barn_id, fl.barn_id) = b.id
                    LEFT JOIN alert_thresholds loc_thr
                        ON loc_thr.scope_type = 'feeding_location'
                        AND loc_thr.scope_id::text = fl.feeding_location_id::text
                        AND loc_thr.key = 'low_feed_percent'
                    LEFT JOIN alert_thresholds glob_thr
                        ON glob_thr.scope_type = 'global'
                        AND glob_thr.scope_id = %s
                        AND glob_thr.key = 'low_feed_percent'
                    WHERE tr.reading_kind = 'feed_level_percentage'
                      AND fl.is_hidden = FALSE
                """
                query += " ORDER BY fl.feeding_location_id, tr.time DESC NULLS LAST"
                cursor.execute(query, (GLOBAL_SCOPE_ID,))
                return cursor.fetchall()
    
    def get_weather_data_for_barn(self, barn_id: str):
        """Get latest weather data for a barn"""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        wo.obs_time,
                        wo.temperature,
                        wo.humidity,
                        wo.thi
                    FROM weather_observations wo
                    INNER JOIN farm_management_farmparcel b ON wo.barn_id = b.id
                    WHERE b.id = %s
                    ORDER BY wo.obs_time DESC
                    LIMIT 1
                """, (barn_id,))
                return cursor.fetchone()
    

    def get_thresholds(self, scope_type: str, scope_id: str = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if scope_type == "global" and not scope_id:
                    scope_id = GLOBAL_SCOPE_ID

                if scope_id:
                    cursor.execute(
                        """
                        SELECT key, value
                        FROM alert_thresholds
                        WHERE scope_type = %s AND scope_id = %s
                        """,
                        (scope_type, scope_id)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT key, value
                        FROM alert_thresholds
                        WHERE scope_type = %s AND scope_id IS NULL
                        """,
                        (scope_type,)
                    )
                rows = cursor.fetchall()
                return {row["key"]: row["value"] for row in rows} if rows else {}

    def upsert_thresholds(
        self,
        scope_type: str,
        scope_id: str,
        thresholds: dict,
        updated_by: int = None
    ):
        if not thresholds:
            return {}
        if scope_type == "global" and not scope_id:
            scope_id = GLOBAL_SCOPE_ID
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    for key, value in thresholds.items():
                        cursor.execute(
                            """
                            INSERT INTO alert_thresholds
                                (scope_type, scope_id, key, value, updated_at, updated_by)
                            VALUES (%s, %s, %s, %s, NOW(), %s)
                            ON CONFLICT (scope_type, scope_id, key)
                            DO UPDATE SET value = EXCLUDED.value,
                                          updated_at = NOW(),
                                          updated_by = EXCLUDED.updated_by
                            """,
                            (scope_type, scope_id, key, Json(value), updated_by)
                        )
                    conn.commit()
                return self.get_thresholds(scope_type, scope_id)
            except Exception as e:
                conn.rollback()
                logger.error(f"Error upserting thresholds: {e}")
                raise

    def get_threshold_value(
        self,
        key: str,
        barn_id: str = None,
        feeding_location_id: str = None,
        default=None
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if feeding_location_id:
                    cursor.execute(
                        """
                        SELECT value
                        FROM alert_thresholds
                        WHERE scope_type = 'feeding_location'
                            AND scope_id = %s
                            AND key = %s
                        """,
                        (feeding_location_id, key)
                    )
                    row = cursor.fetchone()
                    if row:
                        return row["value"]

                cursor.execute(
                    """
                    SELECT value
                    FROM alert_thresholds
                    WHERE scope_type = 'global'
                        AND scope_id = %s
                        AND key = %s
                    """,
                    (GLOBAL_SCOPE_ID, key)
                )
                row = cursor.fetchone()
                if row:
                    return row["value"]
                return default
    
    
    def save_alert(self, alert_data: dict):
        """Save alert to database"""
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    alert_id = str(uuid.uuid4())
                    
                    cursor.execute("""
                        INSERT INTO alerts (
                            alert_id, alert_type, severity, barn_id, barn_name,
                            feeding_location_id, location_name, alert_data, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING alert_id, created_at
                    """, (
                        alert_id,
                        alert_data.get('alert_type'),
                        alert_data.get('severity'),
                        alert_data.get('barn_id'),
                        alert_data.get('barn_name'),
                        alert_data.get('feeding_location_id'),
                        alert_data.get('location_name'),
                        json.dumps(alert_data),
                        'active'
                    ))
                    
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error saving alert: {e}")
                raise
    
    
    def upsert_predicted_alert(self, alert_data: dict, dedupe_key: str):
        """Insert-or-update one predicted alert keyed by dedupe_key.

        The partial unique index uq_predicted_alert_dedupe (origin='predicted' AND
        status='active') makes ON CONFLICT target the single live row per key. A
        forecast that shifts the crossing time or escalates severity UPDATES that
        row and bumps cycles_seen (the debounce counter) rather than spawning a new
        one. Returns alert_id, cycles_seen, email_sent_at, severity, created_at."""
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    alert_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO alerts (
                            alert_id, alert_type, severity, barn_id, barn_name,
                            feeding_location_id, location_name, alert_data, status,
                            origin, predicted_for, dedupe_key,
                            cycles_seen, first_seen_at, last_seen_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active',
                                'predicted', %s, %s, 1, NOW(), NOW())
                        ON CONFLICT (dedupe_key) WHERE origin = 'predicted' AND status = 'active'
                        DO UPDATE SET
                            severity = EXCLUDED.severity,
                            predicted_for = EXCLUDED.predicted_for,
                            alert_data = EXCLUDED.alert_data,
                            barn_name = EXCLUDED.barn_name,
                            location_name = EXCLUDED.location_name,
                            cycles_seen = alerts.cycles_seen + 1,
                            last_seen_at = NOW()
                        RETURNING alert_id, cycles_seen, email_sent_at, severity, created_at
                        """,
                        (
                            alert_id,
                            alert_data.get("alert_type"),
                            alert_data.get("severity"),
                            alert_data.get("barn_id"),
                            alert_data.get("barn_name"),
                            alert_data.get("feeding_location_id"),
                            alert_data.get("location_name"),
                            json.dumps(alert_data, default=str),
                            alert_data.get("predicted_for"),
                            dedupe_key,
                        ),
                    )
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error upserting predicted alert: {e}")
                raise

    def get_active_predicted_alerts(self, barn_id: str = None):
        """Active predicted alerts, used by the engine to reap ones whose dedupe_key
        was not re-seen this cycle (when the data source was available)."""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if barn_id:
                    cursor.execute(
                        """
                        SELECT alert_id, dedupe_key, alert_type, barn_id, feeding_location_id
                        FROM alerts
                        WHERE origin = 'predicted' AND status = 'active' AND barn_id = %s
                        """,
                        (barn_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT alert_id, dedupe_key, alert_type, barn_id, feeding_location_id
                        FROM alerts
                        WHERE origin = 'predicted' AND status = 'active'
                        """
                    )
                return cursor.fetchall()

    def mark_alert_emailed(self, alert_id: str):
        """Stamp email_sent_at so a predicted alert emails at most once (Phase 3)."""
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE alerts SET email_sent_at = NOW() WHERE alert_id = %s",
                        (alert_id,),
                    )
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Error marking alert emailed: {e}")
                raise

    def resolve_alert(self, alert_id: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE alerts
                        SET status = 'resolved',
                            resolved_at = CURRENT_TIMESTAMP
                        WHERE alert_id = %s
                    """, (alert_id,))
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Error resolving alert: {e}")
                raise

    def clear_alerts(
        self,
        barn_id: str = None,
        feeding_location_id: str = None,
        alert_type: str = None,
        status: str = None,
        origin: str = None,
        hard_delete: bool = False,
    ) -> int:
        """Bulk clear alerts by filters.

        Args:
            barn_id: Optional barn filter
            feeding_location_id: Optional feeding location filter
            alert_type: Optional alert type filter
            status: Optional status filter (e.g. active/resolved)
            origin: Optional origin filter (observed/predicted)
            hard_delete: If True, permanently delete rows; otherwise mark resolved

        Returns:
            Number of affected alerts
        """
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    where = ["1=1"]
                    params = []

                    if barn_id:
                        where.append("barn_id = %s")
                        params.append(barn_id)

                    if origin:
                        where.append("origin = %s")
                        params.append(origin)

                    if feeding_location_id:
                        where.append("feeding_location_id = %s")
                        params.append(feeding_location_id)

                    if alert_type:
                        where.append("alert_type = %s")
                        params.append(alert_type)

                    if status:
                        where.append("status = %s")
                        params.append(status)

                    where_sql = " AND ".join(where)

                    if hard_delete:
                        cursor.execute(
                            f"""
                            DELETE FROM alerts
                            WHERE {where_sql}
                            """,
                            tuple(params),
                        )
                    else:
                        cursor.execute(
                            f"""
                            UPDATE alerts
                            SET status = 'resolved', resolved_at = NOW()
                            WHERE {where_sql}
                            """,
                            params,
                        )

                    affected = cursor.rowcount or 0
                    conn.commit()
                    return affected
            except Exception as e:
                conn.rollback()
                logger.error(f"Error clearing alerts: {e}")
                return 0

    def delete_old_alerts(self, hours: int) -> int:
        """Permanently delete OBSERVED alerts older than X hours.

        Predicted alerts are excluded — their lifecycle is managed by the engine's
        reaping (resolve when the forecast clears), and deleting an actively
        refreshed prediction would reset its debounce counter."""
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM alerts
                        WHERE created_at < NOW() - INTERVAL '%s hours'
                            AND origin = 'observed'
                        """,
                        (hours,)
                    )
                    affected = cursor.rowcount or 0
                    conn.commit()
                    return affected
            except Exception as e:
                conn.rollback()
                logger.error(f"Error deleting old alerts: {e}")
                return 0

    def get_alerts(
        self,
        barn_id: str = None,
        feeding_location_id: str = None,
        status: str = None,
        origin: str = None,
        limit: int = 100,
        offset: int = 0
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT
                        alert_id,
                        alert_type,
                        severity,
                        barn_id,
                        barn_name,
                        feeding_location_id,
                        location_name,
                        alert_data,
                        status,
                        origin,
                        predicted_for,
                        cycles_seen,
                        created_at,
                        resolved_at
                    FROM alerts
                    WHERE 1=1
                """
                params = []

                if barn_id:
                    query += " AND barn_id = %s"
                    params.append(barn_id)

                if feeding_location_id:
                    query += " AND feeding_location_id = %s"
                    params.append(feeding_location_id)

                if status:
                    query += " AND status = %s"
                    params.append(status)

                if origin:
                    query += " AND origin = %s"
                    params.append(origin)

                query += " ORDER BY created_at DESC"
                query += " LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cursor.execute(query, params)
                return cursor.fetchall()

    def get_alert_by_id(self, alert_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        alert_id,
                        alert_type,
                        severity,
                        barn_id,
                        barn_name,
                        feeding_location_id,
                        location_name,
                        alert_data,
                        status,
                        origin,
                        predicted_for,
                        cycles_seen,
                        created_at,
                        resolved_at
                    FROM alerts
                    WHERE alert_id = %s
                    """,
                    (alert_id,)
                )
                return cursor.fetchone()
    

    def get_recent_alert_for_location(
        self,
        barn_id: str,
        alert_type: str,
        feeding_location_id: str,
        hours: float
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT alert_id, created_at
                    FROM alerts
                    WHERE barn_id = %s
                        AND alert_type = %s
                        AND feeding_location_id = %s
                        AND created_at >= NOW() - INTERVAL '%s hours'
                        AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (barn_id, alert_type, feeding_location_id, hours)
                )
                return cursor.fetchone()

    def get_alert_count_for_location(
        self,
        alert_type: str,
        feeding_location_id: str,
        days: int
    ):
        with self.get_connection_context() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM alerts
                    WHERE alert_type = %s
                        AND feeding_location_id = %s
                        AND created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (alert_type, feeding_location_id, days)
                )
                row = cursor.fetchone()
                return row[0] if row else 0

    def get_recent_alert_for_animal(self, animal_id: str, hours: float):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT alert_id, created_at
                    FROM alerts
                    WHERE alert_type = 'animal_health'
                        AND alert_data->>'animal_id' = %s
                        AND created_at >= NOW() - INTERVAL '%s hours'
                        AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (animal_id, hours)
                )
                return cursor.fetchone()

    def get_recent_alerts_for_location_by_types(
        self,
        feeding_location_id: str,
        alert_types: list,
        hours: float
    ):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT alert_id, alert_type, created_at
                    FROM alerts
                    WHERE feeding_location_id = %s
                        AND alert_type = ANY(%s)
                        AND created_at >= NOW() - INTERVAL '%s hours'
                        AND status = 'active'
                    ORDER BY created_at DESC
                    """,
                    (feeding_location_id, alert_types, hours)
                )
                return cursor.fetchall()

    def get_animal_alerts(self, animal_id: str, days: int = 7):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        alert_id,
                        alert_type,
                        severity,
                        barn_id,
                        barn_name,
                        feeding_location_id,
                        location_name,
                        alert_data,
                        status,
                        created_at,
                        resolved_at
                    FROM alerts
                    WHERE alert_type = 'animal_health'
                        AND alert_data->>'animal_id' = %s
                        AND created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY created_at DESC
                    """,
                    (animal_id, days)
                )
                return cursor.fetchall()

    def get_recent_health_events_by_barn(self, barn_id: str, hours: int):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT e.*, a.barn_id, a.feeding_location_id
                    FROM moohero_events e
                    INNER JOIN animals a ON e.animal_id = a.id
                    WHERE e.event_type = 'HealthProblemEvent'
                        AND a.barn_id = %s
                        AND e.event_time >= NOW() - INTERVAL '%s hours'
                    ORDER BY e.event_time DESC
                    """,
                    (barn_id, hours)
                )
                return cursor.fetchall()

    def get_recent_health_events_by_location(self, feeding_location_id: str, hours: int):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT e.*, a.barn_id, a.feeding_location_id
                    FROM moohero_events e
                    INNER JOIN animals a ON e.animal_id = a.id
                    WHERE e.event_type = 'HealthProblemEvent'
                        AND a.feeding_location_id = %s
                        AND e.event_time >= NOW() - INTERVAL '%s hours'
                    ORDER BY e.event_time DESC
                    """,
                    (feeding_location_id, hours)
                )
                return cursor.fetchall()
    
    
    def get_feed_consumption_stats(self, barn_id: str, days: int = 7):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        DATE(time) as date,
                        feeding_location_id,
                        AVG(numeric_value) as avg_consumption,
                        MIN(numeric_value) as min_consumption,
                        MAX(numeric_value) as max_consumption,
                        COUNT(*) as reading_count
                    FROM telemetry_readings
                    WHERE barn_id = %s
                        AND reading_kind = 'feed_level_percentage'
                        AND time >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(time), feeding_location_id
                    ORDER BY date DESC
                """, (barn_id, days))
                return cursor.fetchall()
    
    def get_recent_alerts(self, barn_id: str, alert_type: str, hours: int):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT alert_id, created_at
                    FROM alerts
                    WHERE barn_id = %s
                        AND alert_type = %s
                        AND created_at >= NOW() - INTERVAL '%s hours'
                        AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (barn_id, alert_type, hours))
                return cursor.fetchone()
    
    def get_recent_barn_scope_alert(self, barn_id: str, alert_type: str, hours: float):
        """Most recent active alert for a barn that is NOT scoped to a feeding
        location (feeding_location_id IS NULL). Lets barn-scope alerts (e.g.
        health_spike at barn level) keep a cooldown independent of location-scope
        rows of the same type."""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT alert_id, created_at
                    FROM alerts
                    WHERE barn_id = %s
                        AND alert_type = %s
                        AND feeding_location_id IS NULL
                        AND created_at >= NOW() - INTERVAL '%s hours'
                        AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (barn_id, alert_type, hours)
                )
                return cursor.fetchone()

    def create_alert(self, barn_id: str, alert_type: str, severity: str, message: str):
        alert_data = {
            "alert_type": alert_type,
            "severity": severity,
            "barn_id": barn_id,
            "message": message
        }
        result = self.save_alert(alert_data)
        created_at = result.get("created_at") if result else datetime.utcnow()
        return {
            "alert_id": result.get("alert_id") if result else None,
            "barn_id": barn_id,
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "created_at": created_at
        }
    
    def get_upcoming_forecasts(self, hours: int = 24):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                try:
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'weather_forecasts'
                            AND column_name IN (
                                'forecast_for',
                                'forecast_time',
                                'temperature',
                                'humidity',
                                'thi',
                                'barn_id'
                            )
                        """
                    )
                    columns = {row["column_name"] for row in cursor.fetchall()}

                    if "forecast_for" in columns:
                        time_column = "forecast_for"
                    elif "forecast_time" in columns:
                        time_column = "forecast_time"
                    else:
                        logger.error("weather_forecasts has neither forecast_for nor forecast_time")
                        return []

                    temperature_expr = "temperature" if "temperature" in columns else "NULL::double precision"
                    humidity_expr = "humidity" if "humidity" in columns else "NULL::double precision"
                    thi_expr = "thi" if "thi" in columns else "NULL::double precision"

                    barn_id_expr = "barn_id" if "barn_id" in columns else "NULL::uuid"

                    cursor.execute(
                        f"""
                        SELECT
                            {barn_id_expr} as barn_id,
                            {time_column} as forecast_for,
                            {temperature_expr} as temperature,
                            {humidity_expr} as humidity,
                            {thi_expr} as thi
                        FROM weather_forecasts
                        WHERE {time_column} >= NOW()
                            AND {time_column} <= NOW() + (%s * INTERVAL '1 hour')
                        ORDER BY {time_column} ASC
                        """,
                        (hours,)
                    )
                    return cursor.fetchall()
                except Exception:
                    logger.exception(
                        "DB get_upcoming_forecasts failed",
                        extra={"hours": hours}
                    )
                    raise
    
    def get_latest_feed_readings(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT DISTINCT ON (fl.feeding_location_id)
                        fl.feeding_location_id,
                        fl.barn_id,
                        fl.name,
                        tr.numeric_value,
                        tr.time
                    FROM feeding_locations fl
                    LEFT JOIN telemetry_readings tr
                        ON fl.feeding_location_id::text = tr.feeding_location_id::text
                    WHERE COALESCE(
                            NULLIF(tr.reading_kind, ''),
                            NULLIF(BTRIM(tr.raw::jsonb ->> 'reading_type'), ''),
                            NULLIF(BTRIM(tr.raw::jsonb ->> 'readingKind'), '')
                        ) = 'feed_level_percentage'
                        AND tr.time >= NOW() - INTERVAL '1 hour'
                    ORDER BY fl.feeding_location_id, tr.time DESC
                """)
                return cursor.fetchall()
    
    
    
    def save_weather_observation(self, barn_id: str, temperature: float, humidity: float, thi: float, obs_time: datetime):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                obs_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO weather_observations (obs_id, barn_id, temperature, humidity, thi, obs_time)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (obs_id, barn_id, temperature, humidity, thi, obs_time))
                conn.commit()
    def get_weather_history(self, barn_id: str, hours: int = 24, start_time=None, end_time=None,
                            bucket_minutes: int = 60):
        bucket_minutes = max(1, min(int(bucket_minutes), 1440))
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT
                        date_bin(
                            make_interval(mins => %s),
                            time AT TIME ZONE 'Europe/Ljubljana',
                            TIMESTAMP '2000-01-01'
                        ) AT TIME ZONE 'UTC' AS obs_time,
                        AVG(temperature) AS temperature,
                        AVG(humidity) AS humidity,
                        AVG((1.8 * temperature + 32) - (0.55 - 0.0055 * humidity) * (1.8 * temperature - 26)) AS thi
                    FROM telemetry_readings
                    WHERE barn_id = %s
                """
                params = [bucket_minutes, barn_id]
                if start_time:
                    query += " AND time >= %s"
                    params.append(start_time)
                else:
                    query += " AND time >= NOW() - INTERVAL '%s hours'"
                    params.append(hours)
                
                if end_time:
                    query += " AND time <= %s"
                    params.append(end_time)
                
                query += """
                        AND temperature IS NOT NULL
                    GROUP BY 1
                    ORDER BY obs_time ASC
                """
                cursor.execute(query, tuple(params))
                return cursor.fetchall()
    
    def get_calendar_activity_types(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, name, description
                    FROM farm_activities_farmcalendaractivitytype
                    ORDER BY name
                """)
                return cursor.fetchall()
    
    def create_password_reset_token(self, user_id: str, token: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    from datetime import datetime, timedelta
                    expires_at = datetime.utcnow() + timedelta(hours=1)
                    
                    cursor.execute("""
                        INSERT INTO password_reset_tokens (user_id, token, expires_at)
                        VALUES (%s, %s, %s)
                        RETURNING token, expires_at
                    """, (user_id, token, expires_at))
                    
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error creating password reset token: {e}")
                raise
    
    def validate_reset_token(self, token: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                from datetime import datetime
                cursor.execute("""
                    SELECT user_id, expires_at, used
                    FROM password_reset_tokens
                    WHERE token = %s
                """, (token,))
                
                result = cursor.fetchone()
                if not result:
                    return None
                
                if result['used']:
                    return None
                
                if result['expires_at'] < datetime.utcnow():
                    return None
                
                return result['user_id']
    
    def mark_reset_token_used(self, token: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE password_reset_tokens
                        SET used = TRUE
                        WHERE token = %s
                    """, (token,))
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Error marking reset token as used: {e}")
                raise
    
    def update_user_password(self, user_id: str, new_password: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    hashed_password = self.make_django_password(new_password)

                    cursor.execute("""
                        UPDATE auth_user
                        SET password = %s
                        WHERE id = %s
                    """, (hashed_password, user_id))
                    
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Error updating user password: {e}")
                raise
    
    def get_user_email_by_email(self, email: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, email
                    FROM auth_user
                    WHERE email = %s
                """, (email,))
                return cursor.fetchone()
    
    def create_calendar_activities(self, activities: list):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    created_activities = []
                    for activity in activities:
                        activity_id = str(uuid.uuid4())
                        cursor.execute("""
                            INSERT INTO farm_activities_farmcalendaractivity 
                            (id, title, start_datetime, end_datetime, details, 
                             responsible_agent, activity_type_id, parent_activity_id, parcel_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id, title, start_datetime, end_datetime, details, 
                                      responsible_agent, activity_type_id, parent_activity_id, parcel_id
                        """, (
                            activity_id,
                            activity.get('title'),
                            activity.get('start_datetime'),
                            activity.get('end_datetime'),
                            activity.get('details'),
                            activity.get('responsible_agent'),
                            activity.get('activity_type_id'),
                            activity.get('parent_activity_id'),
                            activity.get('parcel_id')
                        ))
                        created_activities.append(cursor.fetchone())
                    
                    conn.commit()
                    return created_activities
            except Exception as e:
                conn.rollback()
                logger.error(f"Error creating calendar activities: {e}")
                raise

    def create_one_time_feeding_activity(
        self,
        barn_id: str,
        feeding_location_id: str,
        start_datetime,
        end_datetime,
        title: str,
        notes: str,
        quantity_kg: float
    ):
        if quantity_kg:
            title = f"{title} ({quantity_kg:.2f} kg)"
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT id FROM farm_activities_farmcalendaractivitytype
                        WHERE name = 'Feeding'
                        """
                    )
                    activity_type = cursor.fetchone()
                    if not activity_type:
                        raise ValueError("Feeding activity type not found")

                    activity_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO farm_activities_farmcalendaractivity
                        (id, title, start_datetime, end_datetime, details,
                         responsible_agent, activity_type_id, parent_activity_id, parcel_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, title, start_datetime, end_datetime, details,
                                  activity_type_id, parcel_id
                        """,
                        (
                            activity_id,
                            title,
                            start_datetime,
                            end_datetime,
                            notes,
                            None,
                            activity_type["id"],
                            None,
                            barn_id
                        )
                    )
                    calendar_activity = cursor.fetchone()

                    cursor.execute(
                        """
                        INSERT INTO feeding_schedules
                        (barn_id, feeding_location_id, schedule_name, days_of_week,
                         time_start, time_end, quantity_kg, notes, farm_calendar_activity_id,
                         actual_feed_datetime, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                        RETURNING id, barn_id, feeding_location_id, schedule_name,
                                  time_start, time_end, quantity_kg, notes, is_active,
                                  farm_calendar_activity_id, actual_feed_datetime
                        """,
                        (
                            barn_id,
                            feeding_location_id,
                            title,
                            [],
                            start_datetime.strftime("%H:%M:%S"),
                            end_datetime.strftime("%H:%M:%S"),
                            quantity_kg,
                            notes,
                            activity_id,
                            start_datetime
                        )
                    )
                    schedule = cursor.fetchone()
                    conn.commit()
                    return {
                        "calendar_activity": calendar_activity,
                        "schedule": schedule
                    }
            except Exception as e:
                conn.rollback()
                logger.error(f"Error creating one-time feeding activity: {e}")
                raise
    
    def get_calendar_activities(self, parcel_id=None, start_date=None, end_date=None, activity_type_id=None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT id, title, start_datetime, end_datetime, details,
                           responsible_agent, activity_type_id, parent_activity_id, parcel_id
                    FROM farm_activities_farmcalendaractivity
                    WHERE 1=1
                """
                params = []
                
                if parcel_id:
                    query += " AND parcel_id = %s"
                    params.append(parcel_id)
                
                if start_date:
                    query += " AND start_datetime >= %s"
                    params.append(start_date)
                
                if end_date:
                    query += " AND end_datetime <= %s"
                    params.append(end_date)
                
                if activity_type_id:
                    query += " AND activity_type_id = %s"
                    params.append(activity_type_id)
                
                query += " ORDER BY start_datetime ASC"
                
                cursor.execute(query, params)
                return cursor.fetchall()

    def get_farm_calendar_feeding_schedules(
        self,
        barn_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 500,
        offset: int = 0,
    ):
        """
        Fetch 'Feeding' activities directly from the Farm Calendar activities table.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM farm_activities_farmcalendaractivitytype WHERE name = 'Feeding'"
                )
                feeding_type = cursor.fetchone()

                if not feeding_type:
                    return []

                query = """
                    SELECT
                        a.id AS activity_id,
                        a.title,
                        a.start_datetime,
                        a.end_datetime,
                        a.details,
                        a.parcel_id AS barn_id,
                        a.parent_activity_id,
                        a.activity_type_id
                    FROM farm_activities_farmcalendaractivity a
                    WHERE a.activity_type_id = %s
                """
                params = [feeding_type["id"]]

                if barn_id:
                    query += " AND a.parcel_id = %s"
                    params.append(barn_id)

                if start_date:
                    query += " AND a.start_datetime >= %s"
                    params.append(start_date)

                if end_date:
                    query += " AND a.start_datetime <= %s"
                    params.append(end_date)

                query += " ORDER BY a.start_datetime ASC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                if not rows:
                    return []

                schedules = []
                for r in rows:
                    dt = r.get("start_datetime")
                    date_str = dt.date().isoformat() if dt else None
                    time_str = dt.strftime("%H:%M:%S") if dt else None
                    schedules.append(
                        {
                            "activity_id": str(r.get("activity_id")) if r.get("activity_id") is not None else None,
                            "barn_id": str(r.get("barn_id")) if r.get("barn_id") is not None else None,
                            "title": r.get("title"),
                            "start_datetime": dt.isoformat() if dt else None,
                            "end_datetime": r.get("end_datetime").isoformat() if r.get("end_datetime") else None,
                            "date": date_str,
                            "time": time_str,
                            "details": r.get("details"),
                            "parent_activity_id": str(r.get("parent_activity_id")) if r.get("parent_activity_id") else None,
                        }
                    )

                return schedules
    
    def delete_calendar_activity(self, activity_id: str):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM farm_activities_farmcalendaractivity
                        WHERE id = %s
                    """, (activity_id,))
                    conn.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                conn.rollback()
                logger.error(f"Error deleting calendar activity: {e}")
                raise
    
    def create_feeding_schedule(self, barn_id: str, feeding_location_id: str, schedule_name: str,
                                days_of_week: list, time_start: str, time_end: str,
                                quantity_kg: float = None, notes: str = None):
        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("""
                        INSERT INTO feeding_schedules
                        (barn_id, feeding_location_id, schedule_name, days_of_week, time_start, time_end, quantity_kg, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, barn_id, feeding_location_id, schedule_name, days_of_week,
                                  time_start, time_end, quantity_kg, notes, is_active, created_at, updated_at
                    """, (barn_id, feeding_location_id, schedule_name, days_of_week, time_start, time_end, quantity_kg, notes))
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error creating feeding schedule: {e}")
                raise
    
    def get_feeding_schedules(self, barn_id: str = None, feeding_location_id: str = None, 
                             is_active: bool = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT fs.id, fs.barn_id, fs.feeding_location_id, fs.schedule_name,
                           fs.days_of_week, fs.time_start, fs.time_end, fs.quantity_kg, fs.notes,
                           fs.is_active, fs.created_at, fs.updated_at,
                           fl.name as location_name
                    FROM feeding_schedules fs
                    LEFT JOIN feeding_locations fl ON fs.feeding_location_id = fl.feeding_location_id
                    WHERE coalesce(array_length(fs.days_of_week, 1), 0) > 0
                """
                params = []
                
                if barn_id:
                    query += " AND fs.barn_id = %s"
                    params.append(barn_id)
                
                if feeding_location_id:
                    query += " AND fs.feeding_location_id = %s"
                    params.append(feeding_location_id)
                
                if is_active is not None:
                    query += " AND fs.is_active = %s"
                    params.append(is_active)
                
                query += " ORDER BY fs.created_at DESC"
                cursor.execute(query, params)
                return cursor.fetchall()
    
    def get_feeding_schedule_by_id(self, schedule_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT fs.id, fs.barn_id, fs.feeding_location_id, fs.schedule_name,
                           fs.days_of_week, fs.time_start, fs.time_end, fs.quantity_kg, fs.notes,
                           fs.is_active, fs.created_at, fs.updated_at,
                           fl.name as location_name
                    FROM feeding_schedules fs
                    LEFT JOIN feeding_locations fl ON fs.feeding_location_id = fl.feeding_location_id
                    WHERE fs.id = %s
                """, (schedule_id,))
                return cursor.fetchone()
    
    def update_feeding_schedule(self, schedule_id: str, schedule_name: str = None,
                               days_of_week: list = None, time_start: str = None,
                               time_end: str = None, quantity_kg: float = None,
                               notes: str = None, is_active: bool = None):
        """Partially update a feeding schedule.

        Only the fields passed (non-None) are changed. Returns the full updated row,
        or None if no schedule with that id exists.

        Note: calendar events already generated at the previous time window are not
        purged here; the caller regenerates events, and duplicate-detection keeps new
        events from being created twice. Stale events at an old window are left in
        place (see feeding_event_generator).
        """
        fields = {
            "schedule_name": schedule_name,
            "days_of_week": days_of_week,
            "time_start": time_start,
            "time_end": time_end,
            "quantity_kg": quantity_kg,
            "notes": notes,
            "is_active": is_active,
        }
        set_fields = {k: v for k, v in fields.items() if v is not None}

        with self.get_connection_context() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if set_fields:
                        assignments = ", ".join(f"{k} = %s" for k in set_fields)
                        params = list(set_fields.values()) + [schedule_id]
                        cursor.execute(
                            f"""
                            UPDATE feeding_schedules
                            SET {assignments}, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                            """,
                            params,
                        )
                        if cursor.rowcount == 0:
                            conn.rollback()
                            return None

                    cursor.execute(
                        """
                        SELECT fs.id, fs.barn_id, fs.feeding_location_id, fs.schedule_name,
                               fs.days_of_week, fs.time_start, fs.time_end, fs.quantity_kg,
                               fs.notes, fs.is_active, fs.created_at, fs.updated_at,
                               fl.name as location_name
                        FROM feeding_schedules fs
                        LEFT JOIN feeding_locations fl ON fs.feeding_location_id = fl.feeding_location_id
                        WHERE fs.id = %s
                        """,
                        (schedule_id,),
                    )
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Error updating feeding schedule: {e}")
                raise
    
    def get_active_schedules_for_generation(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT fs.id, fs.barn_id, fs.feeding_location_id, fs.schedule_name,
                           fs.days_of_week, fs.time_start, fs.time_end, fs.quantity_kg, fs.notes,
                           fl.name as location_name
                    FROM feeding_schedules fs
                    LEFT JOIN feeding_locations fl ON fs.feeding_location_id = fl.feeding_location_id
                    WHERE fs.is_active = true
                    ORDER BY fs.barn_id, fs.feeding_location_id, fs.time_start
                """)
                return cursor.fetchall()
    
    def sync_farm_calendar_feeding_activities(self, days_back: int = 7, days_ahead: int = 30):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id FROM farm_activities_farmcalendaractivitytype
                    WHERE name = 'Feeding'
                """)
                feeding_type = cursor.fetchone()
                
                if not feeding_type:
                    return 0
                
                from datetime import datetime, timedelta
                start_date = datetime.now() - timedelta(days=days_back)
                end_date = datetime.now() + timedelta(days=days_ahead)
                
                cursor.execute("""
                    SELECT 
                        a.id as activity_id,
                        a.title,
                        a.start_datetime,
                        a.end_datetime,
                        a.parcel_id as barn_id,
                        a.details,
                        a.parent_activity_id
                    FROM farm_activities_farmcalendaractivity a
                    INNER JOIN farm_management_farmparcel p ON a.parcel_id = p.id
                    WHERE a.activity_type_id = %s
                    AND a.start_datetime >= %s
                    AND a.start_datetime <= %s
                    AND p.parcel_type = 'barn'
                    AND p.deleted_at IS NULL
                    ORDER BY a.start_datetime
                """, (feeding_type['id'], start_date, end_date))
                
                activities = cursor.fetchall()
                synced_count = 0
                
                for activity in activities:
                    cursor.execute("""
                        SELECT id FROM feeding_schedules
                        WHERE farm_calendar_activity_id = %s
                    """, (activity['activity_id'],))
                    
                    if cursor.fetchone():
                        continue
                    
                    end_dt = activity['end_datetime'] or (
                        activity['start_datetime'] + timedelta(hours=1)
                    )
                    cursor.execute("""
                        INSERT INTO feeding_schedules
                        (barn_id, feeding_location_id, schedule_name, days_of_week,
                         time_start, time_end, notes, farm_calendar_activity_id, actual_feed_datetime, is_active)
                        VALUES (%s, NULL, %s, '{}', %s, %s, %s, %s, %s, true)
                    """, (
                        activity['barn_id'],
                        activity['title'] or 'Farm Calendar Feeding',
                        activity['start_datetime'].strftime('%H:%M:%S'),
                        end_dt.strftime('%H:%M:%S'),
                        activity['details'],
                        activity['activity_id'],
                        activity['start_datetime']
                    ))
                    synced_count += 1
                
                conn.commit()
                logger.info(f"Synced {synced_count} feeding activities from Farm Calendar")
                return synced_count
    
    def check_feeding_event_exists(self, feeding_location_id: str, start_datetime, activity_type_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM farm_activities_farmcalendaractivity
                    WHERE parcel_id = %s
                    AND start_datetime = %s
                    AND activity_type_id = %s
                """, (feeding_location_id, start_datetime, activity_type_id))
                result = cursor.fetchone()
                return result[0] > 0 if result else False
    
    
    def get_moohero_farm_mappings(self):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT mfm.*, f.name as farm_name
                    FROM moohero_farm_mapping mfm
                    LEFT JOIN farm_management_farm f ON mfm.farm_id = f.id
                    ORDER BY mfm.created_at DESC
                """)
                return cursor.fetchall()

    def get_moohero_farm_links(self):
        """Return {moohero_farm_id: farm_id} for all established links."""
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT moohero_farm_id, farm_id
                    FROM moohero_farm_mapping
                    WHERE farm_id IS NOT NULL
                """)
                return {row["moohero_farm_id"]: str(row["farm_id"]) for row in cursor.fetchall()}

    def upsert_moohero_farm_link(self, moohero_farm_id: int, farm_id: str, moohero_farm_name: str = None):
        """Link a MooHero farm to a local (Farm Calendar) farm.

        This is what activates per-farm MooHero event scoping and restores the
        farm's moohero_id on the /farms response. Keyed on moohero_farm_id.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO moohero_farm_mapping (id, moohero_farm_id, moohero_farm_name, farm_id)
                    VALUES (gen_random_uuid(), %s, %s, %s)
                    ON CONFLICT (moohero_farm_id) DO UPDATE SET
                        moohero_farm_name = EXCLUDED.moohero_farm_name,
                        farm_id = EXCLUDED.farm_id,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id, moohero_farm_id, moohero_farm_name, farm_id
                """, (moohero_farm_id, moohero_farm_name, farm_id))
                row = cursor.fetchone()
                conn.commit()
                return row

    def delete_moohero_farm_link(self, moohero_farm_id: int):
        """Remove a MooHero<->farm link."""
        with self.get_connection_context() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM moohero_farm_mapping WHERE moohero_farm_id = %s",
                    (moohero_farm_id,)
                )
                conn.commit()
                return cursor.rowcount
    
    def create_animal(self, animal_name: str, barn_id: str, moohero_collar_unique_id: str = None,
                     feeding_location_id: str = None, animal_type: str = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                animal_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO animals (id, animal_name, barn_id, moohero_collar_unique_id, 
                                       feeding_location_id, animal_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, animal_name, barn_id, moohero_collar_unique_id, 
                             feeding_location_id, animal_type, health_score, created_at
                """, (animal_id, animal_name, barn_id, moohero_collar_unique_id,
                     feeding_location_id, animal_type))
                result = cursor.fetchone()

                # Link any already-stored events for this collar to the new animal.
                # MooHero events are synced in keyed by collar and only get an
                # animal_id at insert time (create_moohero_event); events that
                # arrived before this animal existed are stored with animal_id
                # NULL, so without this backfill the animal would show 0 events
                # until the next scheduled re-sync.
                if moohero_collar_unique_id:
                    cursor.execute("""
                        UPDATE moohero_events
                        SET animal_id = %s
                        WHERE moohero_collar_unique_id = %s
                          AND animal_id IS NULL
                    """, (animal_id, moohero_collar_unique_id))

                conn.commit()
                return result

    def get_animals(self, barn_id: str = None, feeding_location_id: str = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT a.*, b.identifier as barn_name, fl.name as feeding_location_name
                    FROM animals a
                    LEFT JOIN farm_management_farmparcel b ON a.barn_id = b.id
                    LEFT JOIN feeding_locations fl ON a.feeding_location_id = fl.feeding_location_id
                    WHERE 1=1
                """
                params = []
                
                if barn_id:
                    query += " AND a.barn_id = %s"
                    params.append(barn_id)
                
                if feeding_location_id:
                    query += " AND a.feeding_location_id = %s"
                    params.append(feeding_location_id)
                
                query += " ORDER BY a.created_at DESC"
                cursor.execute(query, params)
                return cursor.fetchall()
    
    def get_animal_by_id(self, animal_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT a.*, b.identifier as barn_name, fl.name as feeding_location_name
                    FROM animals a
                    LEFT JOIN farm_management_farmparcel b ON a.barn_id = b.id
                    LEFT JOIN feeding_locations fl ON a.feeding_location_id = fl.feeding_location_id
                    WHERE a.id = %s
                """, (animal_id,))
                return cursor.fetchone()
    
    def update_animal_collar(self, animal_id: str, moohero_collar_unique_id: str):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    UPDATE animals
                    SET moohero_collar_unique_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, animal_name, moohero_collar_unique_id
                """, (moohero_collar_unique_id, animal_id))
                result = cursor.fetchone()
                conn.commit()
                return result
    
    def update_animal_health_score(self, animal_id: str, health_score: float):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    UPDATE animals
                    SET health_score = %s, 
                        last_health_update = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, health_score, last_health_update
                """, (health_score, animal_id))
                result = cursor.fetchone()
                conn.commit()
                return result
    
    def create_moohero_event(self, event_id: str, event_type: str, moohero_collar_unique_id: str,
                            event_time, severity: str = None, details: dict = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id FROM animals WHERE moohero_collar_unique_id = %s
                """, (moohero_collar_unique_id,))
                animal = cursor.fetchone()
                animal_id = animal['id'] if animal else None
                
                cursor.execute("""
                    INSERT INTO moohero_events (event_id, event_type, moohero_collar_unique_id,
                                               animal_id, event_time, severity, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO UPDATE
                    SET event_type = EXCLUDED.event_type,
                        severity = EXCLUDED.severity,
                        details = EXCLUDED.details,
                        moohero_collar_unique_id = EXCLUDED.moohero_collar_unique_id,
                        animal_id = EXCLUDED.animal_id
                    RETURNING id, event_id, event_type, animal_id, event_time, severity, created_at
                """, (event_id, event_type, moohero_collar_unique_id, animal_id, 
                     event_time, severity, json.dumps(details) if details else None))
                result = cursor.fetchone()
                conn.commit()
                return result
    
    def get_moohero_events(self, animal_id: str = None, event_type: str = None, days: int = 7):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT e.*, a.animal_name
                    FROM moohero_events e
                    LEFT JOIN animals a ON e.animal_id = a.id
                    WHERE e.event_time >= NOW() - INTERVAL '%s days'
                """
                params = [days]
                
                if animal_id:
                    query += " AND e.animal_id = %s"
                    params.append(animal_id)
                
                if event_type:
                    query += " AND e.event_type = %s"
                    params.append(event_type)
                
                query += " ORDER BY e.event_time DESC"
                cursor.execute(query, params)
                return cursor.fetchall()

    def get_moohero_events_by_collars(
        self,
        collar_ids: list,
        event_type: str = None,
        days: int = 7
    ):
        if not collar_ids:
            return []

        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT e.*, a.animal_name
                    FROM moohero_events e
                    LEFT JOIN animals a ON e.animal_id = a.id
                    WHERE e.event_time >= NOW() - INTERVAL '%s days'
                      AND e.moohero_collar_unique_id = ANY(%s)
                """
                params = [days, collar_ids]

                if event_type:
                    query += " AND e.event_type = %s"
                    params.append(event_type)

                query += " ORDER BY e.event_time DESC"
                cursor.execute(query, params)
                return cursor.fetchall()
    
    def log_moohero_sync(self, sync_type: str, status: str, records_synced: int = None, 
                        error_message: str = None, started_at = None):
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO moohero_sync_log (sync_type, status, records_synced, error_message, 
                                                 started_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id, sync_type, status, records_synced, started_at, completed_at
                """, (sync_type, status, records_synced, error_message, started_at or datetime.now()))
                result = cursor.fetchone()
                conn.commit()
                return result

    def get_barn_animal_stats(self, barn_id: str = None, days: int = 7):
        """
        Return per-barn summary: animal count, total health events, total heat events.
        Optionally filtered to a single barn.
        """
        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT
                        b.id AS barn_id,
                        b.identifier AS barn_name,
                        COUNT(DISTINCT a.id) AS animal_count,
                        COUNT(DISTINCT e.id) FILTER (WHERE e.event_time >= NOW() - (%s * INTERVAL '1 day')) AS total_health_events,
                        COUNT(DISTINCT e.id) FILTER (
                            WHERE e.event_time >= NOW() - (%s * INTERVAL '1 day')
                            AND LOWER(e.event_type) LIKE '%%heat%%'
                        ) AS total_heat_events
                    FROM farm_management_farmparcel b
                    LEFT JOIN animals a ON a.barn_id = b.id
                    LEFT JOIN moohero_events e ON e.animal_id = a.id
                    WHERE 1=1
                """
                params = [days, days]

                if barn_id:
                    query += " AND b.id = %s"
                    params.append(barn_id)

                query += " GROUP BY b.id, b.identifier ORDER BY b.identifier"
                cursor.execute(query, params)
                return cursor.fetchall()

    def get_animal_event_summary(self, animal_ids: list, days: int = 7):
        """
        Return per-animal event count summary for the given list of animal IDs.
        Returns a dict keyed by animal_id.
        """
        if not animal_ids:
            return {}

        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        e.animal_id::text,
                        COUNT(*) AS total_events,
                        COUNT(*) FILTER (WHERE LOWER(e.event_type) LIKE '%%heat%%') AS heat_events,
                        MAX(e.event_time) AS last_event_time
                    FROM moohero_events e
                    WHERE e.animal_id::text = ANY(%s)
                        AND e.event_time >= NOW() - (%s * INTERVAL '1 day')
                    GROUP BY e.animal_id::text
                """, (animal_ids, days))
                rows = cursor.fetchall()
                return {str(row["animal_id"]): row for row in rows}

    def update_animal(self, animal_id: str, barn_id: str = None,
                      feeding_location_id: str = None,
                      moohero_collar_unique_id: str = None,
                      animal_name: str = None,
                      animal_type: str = None):
        """Update any combination of animal fields."""
        fields = []
        params = []

        if barn_id is not None:
            fields.append("barn_id = %s")
            params.append(barn_id)
        if feeding_location_id is not None:
            fields.append("feeding_location_id = %s")
            params.append(feeding_location_id)
        if moohero_collar_unique_id is not None:
            fields.append("moohero_collar_unique_id = %s")
            params.append(moohero_collar_unique_id)
        if animal_name is not None:
            fields.append("animal_name = %s")
            params.append(animal_name)
        if animal_type is not None:
            fields.append("animal_type = %s")
            params.append(animal_type)

        if not fields:
            return None

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(animal_id)

        with self.get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(f"""
                    UPDATE animals
                    SET {', '.join(fields)}
                    WHERE id = %s
                    RETURNING id, animal_name, barn_id, feeding_location_id,
                              moohero_collar_unique_id, animal_type, health_score, updated_at
                """, params)
                result = cursor.fetchone()

                # If the collar was (re)assigned, link its orphaned events to
                # this animal so the change is reflected immediately (mirrors the
                # backfill done in create_animal).
                if moohero_collar_unique_id is not None:
                    cursor.execute("""
                        UPDATE moohero_events
                        SET animal_id = %s
                        WHERE moohero_collar_unique_id = %s
                          AND animal_id IS NULL
                    """, (animal_id, moohero_collar_unique_id))

                conn.commit()
                return result

