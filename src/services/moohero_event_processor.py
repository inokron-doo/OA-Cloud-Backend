from datetime import datetime, timedelta, timezone
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from src.utils.db import PGDB
import logging

logger = logging.getLogger(__name__)

SYNC_INTERVAL_HOURS = int(os.getenv("MOOHERO_SYNC_INTERVAL_HOURS", "24"))


class MooHeroEventProcessor:
    
    def __init__(self):
        self.db = PGDB()
        self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self.is_running = False
        self.sync_interval_hours = SYNC_INTERVAL_HOURS
        self.sync_job_id = "moohero_event_sync"
        self.startup_sync_job_id = "moohero_event_sync_startup"

    def _as_float(self, value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _as_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_event_time(self, raw_time):
        if not raw_time:
            return datetime.now()
        if isinstance(raw_time, datetime):
            return raw_time
        if isinstance(raw_time, str):
            try:
                # Handles both ISO strings and values like "2026-03-16 11:50:00 +0100".
                return datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Unable to parse event time '{raw_time}', using now()")
        return datetime.now()

    def _normalize_event_type(self, event_data: dict) -> str:
        return (
            event_data.get('event_type')
            or event_data.get('type')
            or ''
        )

    def _extract_collar_id(self, event_data: dict):
        return (
            event_data.get('collar_unique_id')
            or event_data.get('collar_id')
        )

    def _build_event_details(self, event_data: dict, extra: dict = None) -> dict:
        animal_id = event_data.get("animal_id")
        animal_data = event_data.get("animal")
        if not animal_id and isinstance(animal_data, dict):
            animal_id = animal_data.get("id")
            
        details = {
            "moohero_animal_id": animal_id,
            "started_at": event_data.get("started_at"),
            "ended_at": event_data.get("ended_at"),
            "source_type": self._normalize_event_type(event_data),
            "raw_event": event_data,
        }
        if extra:
            details.update(extra)
        return details
    
    def process_health_event(self, event_data: dict):
        try:
            event_id = str(event_data.get('id'))
            collar_id = self._extract_collar_id(event_data)
            event_time = self._parse_event_time(
                event_data.get('occurred_at')
                or event_data.get('started_at')
                or event_data.get('ended_at')
            )
            severity = event_data.get('severity', 'low')
            description = event_data.get('description', '')
            
            self.db.create_moohero_event(
                event_id=event_id,
                event_type='HealthProblemEvent',
                moohero_collar_unique_id=collar_id,
                event_time=event_time,
                severity=severity,
                details=self._build_event_details(
                    event_data,
                    {'description': description}
                )
            )
            
            animal = self._get_animal_by_collar(collar_id)
            if not animal:
                logger.warning(f"No animal found for collar {collar_id}")
                return
            
            health_impact = self._calculate_health_impact(severity)
            self.db.update_animal_health_score(animal['id'], health_impact)

            # No per-event alert: health alerting is now the rate-based health_spike
            # rule in the AlertEngine, which reads these stored events. This processor
            # is a pure ingester.
            logger.info(f"Ingested health event for animal {animal['animal_name']}")
            
        except Exception as e:
            logger.error(f"Error processing health event: {e}")
    
    def process_heat_event(self, event_data: dict):
        try:
            event_id = str(event_data.get('id'))
            collar_id = self._extract_collar_id(event_data)
            event_time = self._parse_event_time(
                event_data.get('occurred_at')
                or event_data.get('started_at')
                or event_data.get('ended_at')
            )
            
            self.db.create_moohero_event(
                event_id=event_id,
                event_type='HeatEvent',
                moohero_collar_unique_id=collar_id,
                event_time=event_time,
                severity=None,
                details=self._build_event_details(
                    event_data,
                    {'breeding_opportunity': True}
                )
            )
            
            animal = self._get_animal_by_collar(collar_id)
            if animal:
                logger.info(f"Heat event detected for animal {animal['animal_name']}")
            
        except Exception as e:
            logger.error(f"Error processing heat event: {e}")

    def process_generic_event(self, event_data: dict):
        try:
            event_id = str(event_data.get('id'))
            event_type = self._normalize_event_type(event_data) or "UnknownEvent"
            collar_id = self._extract_collar_id(event_data)
            event_time = self._parse_event_time(
                event_data.get('occurred_at')
                or event_data.get('started_at')
                or event_data.get('ended_at')
            )

            self.db.create_moohero_event(
                event_id=event_id,
                event_type=event_type,
                moohero_collar_unique_id=collar_id,
                event_time=event_time,
                severity=event_data.get('severity'),
                details=self._build_event_details(event_data)
            )
            logger.info(f"Stored generic MooHero event {event_id} ({event_type})")
        except Exception as e:
            logger.error(f"Error processing generic event: {e}")
    
    def process_events_batch(self, events: list, collar_map: dict = None):
        processed = {'health': 0, 'heat': 0, 'other': 0}
        collar_map = collar_map or {}
        
        for event in events:
            # Dynamically map numeric animal_id to string collar ID if missing
            moohero_animal_id = event.get('animal_id')
            animal_data = event.get('animal')
            if not moohero_animal_id and isinstance(animal_data, dict):
                moohero_animal_id = animal_data.get('id')
                
            if moohero_animal_id and not event.get('collar_unique_id') and not event.get('collar_id'):
                try:
                    mapped_collar = collar_map.get(int(moohero_animal_id))
                    if mapped_collar:
                        event['collar_unique_id'] = mapped_collar
                    else:
                        logger.warning(f"DEBUG: Unmapped event! animal_id={moohero_animal_id} not in collar_map. Available keys: {list(collar_map.keys())[:15]}...")
                        logger.warning(f"DEBUG: Unmapped event payload: {event}")
                except (ValueError, TypeError):
                    pass

            event_type = self._normalize_event_type(event)
            
            if event_type in ['HealthProblemEvent', 'HealthEvent']:
                self.process_health_event(event)
                processed['health'] += 1
            elif event_type == 'HeatEvent':
                self.process_heat_event(event)
                processed['heat'] += 1
            else:
                self.process_generic_event(event)
                processed['other'] += 1
                logger.warning(f"Unknown event type: {event_type}")
        
        return processed
    
    async def sync_events_from_api(self):
        try:
            from src.services.moohero_service import moohero_service
            
            started_at = datetime.now(timezone.utc)
            logger.info("Starting MooHero event sync...")
            
            to_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            from_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')

            mappings = self.db.get_moohero_farm_mappings()
            farm_ids = [m.get('moohero_farm_id') for m in mappings if m.get('moohero_farm_id')]

            all_events = []
            if farm_ids:
                for farm_id in farm_ids:
                    try:
                        farm_events = moohero_service.get_events(
                            farm_id=farm_id,
                            from_date=from_date,
                            to_date=to_date
                        )
                        logger.info(
                            f"Fetched {len(farm_events or [])} MooHero events for farm_id={farm_id}"
                        )
                        if farm_events:
                            all_events.extend(farm_events)
                    except Exception as farm_error:
                        logger.error(f"Failed to fetch MooHero events for farm_id={farm_id}: {farm_error}")
            else:
                all_events = moohero_service.get_events(from_date=from_date, to_date=to_date)

            events = all_events
            
            if not events:
                logger.info("No MooHero events to sync")
                self.db.log_moohero_sync(
                    sync_type='events',
                    status='success',
                    records_synced=0,
                    started_at=started_at
                )
                return
            
            # Fetch collar map dynamically to resolve animal numeric IDs
            try:
                animals = moohero_service.get_all_animals_from_farms()
                logger.info(f"DEBUG: get_all_animals_from_farms returned {len(animals)} animals. Sample: {animals[:1]}")
                collar_map = {}
                for a in animals:
                    unique_id = a.get("unique_id")
                    if unique_id:
                        # 1. Map the collar's own ID
                        collar_id = a.get("id")
                        if collar_id:
                            collar_map[int(collar_id)] = unique_id
                        
                        # 2. Map the nested animal's ID
                        animal_assignment = a.get("animal_assignment")
                        if animal_assignment and isinstance(animal_assignment, dict):
                            animal_info = animal_assignment.get("animal")
                            if animal_info and isinstance(animal_info, dict):
                                animal_id = animal_info.get("id")
                                if animal_id:
                                    collar_map[int(animal_id)] = unique_id
                
                logger.info(f"DEBUG: Built collar_map with {len(collar_map)} entries mapping both collar and animal IDs to unique_id.")
            except Exception as e:
                logger.error(f"Failed to fetch animals for collar mapping: {e}")
                collar_map = {}
            
            processed = self.process_events_batch(events, collar_map=collar_map)
            total = processed['health'] + processed['heat'] + processed['other']

            # Spike detection moved to the AlertEngine (health_spike rule); this
            # processor only ingests events into the DB.
            self.db.log_moohero_sync(
                sync_type='events',
                status='success',
                records_synced=total,
                started_at=started_at
            )
            
            logger.info(
                f"MooHero event sync complete: "
                f"{processed['health']} health, "
                f"{processed['heat']} heat, "
                f"{processed['other']} other"
            )
            
        except Exception as e:
            logger.error(f"MooHero event sync failed: {e}")
            self.db.log_moohero_sync(
                sync_type='events',
                status='failed',
                error_message=str(e),
                started_at=datetime.now(timezone.utc)
            )
    
    def start(self):
        if self.is_running:
            logger.warning("MooHero event processor is already running")
            return

        # Run once shortly after startup to fetch fresh events without waiting for interval.
        self.scheduler.add_job(
            self.sync_events_from_api,
            trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=20)),
            id=self.startup_sync_job_id,
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        
        self.scheduler.add_job(
            self.sync_events_from_api,
            trigger=IntervalTrigger(hours=self.sync_interval_hours),
            id=self.sync_job_id,
            replace_existing=True,
            max_instances=1
        )
        
        self.scheduler.start()
        self.is_running = True
        logger.info(f"MooHero event processor started (interval: {self.sync_interval_hours} hours)")
    
    def stop(self):
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("MooHero event processor stopped")
    
    def _get_animal_by_collar(self, collar_id: str):
        animals = self.db.get_animals()
        for animal in animals:
            if animal.get('moohero_collar_unique_id') == collar_id:
                return animal
        return None
    
    def _calculate_health_impact(self, severity: str) -> float:
        severity_scores = {
            'low': 85.0,
            'medium': 70.0,
            'high': 50.0
        }
        return severity_scores.get(severity, 75.0)
    
moohero_event_processor = MooHeroEventProcessor()

