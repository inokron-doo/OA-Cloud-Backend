import os
import logging
from datetime import datetime, timedelta, time
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.utils.db import PGDB

logger = logging.getLogger(__name__)

class FeedingEventGenerator:
    def __init__(self):
        self.db = PGDB()
        self.scheduler = AsyncIOScheduler()
        self.lookahead_days = int(os.getenv("FEEDING_EVENT_LOOKAHEAD_DAYS", "7"))
        self.generation_day = int(os.getenv("FEEDING_EVENT_GENERATION_DAY", "6"))
        self.generation_hour = int(os.getenv("FEEDING_EVENT_GENERATION_HOUR", "0"))
        self.feeding_activity_type_id = None
        
    async def start(self):
        logger.info("Starting Feeding Event Generator service")
        
        activity_types = self.db.get_calendar_activity_types()
        feeding_type = next((t for t in activity_types if t.get('name', '').lower() == 'feeding'), None)
        
        if not feeding_type:
            logger.warning("'Feeding' activity type not found. Please register it before generating events.")
        else:
            self.feeding_activity_type_id = feeding_type['id']
            logger.info(f"Found Feeding activity type: {self.feeding_activity_type_id}")
        
        self.scheduler.add_job(
            self.generate_weekly_events,
            'cron',
            day_of_week=self.generation_day,
            hour=self.generation_hour,
            minute=0,
            id='weekly_feeding_event_generation'
        )
        
        self.scheduler.start()
        logger.info(f"Scheduled weekly event generation: Every {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][self.generation_day]} at {self.generation_hour:02d}:00")
    
    async def stop(self):
        logger.info("Stopping Feeding Event Generator service")
        self.scheduler.shutdown(wait=False)
    
    async def generate_weekly_events(self):
        try:
            logger.info("Starting weekly feeding event generation...")
            
            if not self.feeding_activity_type_id:
                activity_types = self.db.get_calendar_activity_types()
                feeding_type = next((t for t in activity_types if t.get('name', '').lower() == 'feeding'), None)
                if not feeding_type:
                    logger.error("Cannot generate events: 'Feeding' activity type not found")
                    return
                self.feeding_activity_type_id = feeding_type['id']
            
            schedules = self.db.get_active_schedules_for_generation()
            
            if not schedules:
                logger.info("No active feeding schedules found")
                return
            
            total_generated = 0
            total_skipped = 0
            
            for schedule in schedules:
                generated, skipped = await self._generate_events_for_schedule(schedule)
                total_generated += generated
                total_skipped += skipped
            
            logger.info(f"Weekly event generation complete. Generated: {total_generated}, Skipped (duplicates): {total_skipped}")
        
        except Exception as e:
            logger.error(f"Error during weekly event generation: {e}", exc_info=True)
    
    async def _generate_events_for_schedule(self, schedule):
        generated_count = 0
        skipped_count = 0
        
        try:
            schedule_id = schedule['id']
            days_of_week = schedule['days_of_week']
            time_start = schedule['time_start']
            time_end = schedule['time_end']
            location_name = schedule.get('location_name', 'Unknown Location')
            feeding_location_id = schedule['feeding_location_id']

            start_date = datetime.now().date()
            end_date = start_date + timedelta(days=self.lookahead_days)

            current_date = start_date
            events_to_create = []

            while current_date <= end_date:
                if current_date.weekday() in days_of_week:
                    event_datetime = datetime.combine(current_date, time_start)
                    end_datetime = datetime.combine(current_date, time_end)
                    # A window whose end is at or before its start crosses midnight.
                    if end_datetime <= event_datetime:
                        end_datetime += timedelta(days=1)
                    
                    if not self.db.check_feeding_event_exists(
                        schedule['barn_id'],
                        event_datetime,
                        self.feeding_activity_type_id
                    ):
                        title = f"Feeding - {location_name}"
                        if schedule.get('quantity_kg'):
                            title += f" ({schedule['quantity_kg']} kg)"
                        
                        event_dict = {
                            'title': title,
                            'start_datetime': event_datetime,
                            'end_datetime': end_datetime,
                            'details': schedule.get('notes', f"Auto-generated from schedule: {schedule['schedule_name']}"),
                            'activity_type_id': self.feeding_activity_type_id,
                            'parcel_id': schedule['barn_id'],
                            'responsible_agent': None,
                            'parent_activity_id': None
                        }
                        events_to_create.append(event_dict)
                    else:
                        skipped_count += 1
                
                current_date += timedelta(days=1)
            
            if events_to_create:
                created = self.db.create_calendar_activities(events_to_create)
                generated_count = len(created) if created else 0
                logger.info(f"Schedule {schedule['schedule_name']}: Generated {generated_count} events, Skipped {skipped_count}")
            else:
                logger.info(f"Schedule {schedule['schedule_name']}: All events already exist ({skipped_count} duplicates)")
        
        except Exception as e:
            logger.error(f"Error generating events for schedule {schedule.get('schedule_name', 'Unknown')}: {e}", exc_info=True)
        
        return generated_count, skipped_count
    
    async def generate_events_for_schedule_id(self, schedule_id: str):
        schedule = self.db.get_feeding_schedule_by_id(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")
        
        if not schedule.get('is_active'):
            raise ValueError(f"Schedule {schedule_id} is not active")
        
        if not self.feeding_activity_type_id:
            activity_types = self.db.get_calendar_activity_types()
            feeding_type = next((t for t in activity_types if t.get('name', '').lower() == 'feeding'), None)
            if not feeding_type:
                raise ValueError("'Feeding' activity type not found")
            self.feeding_activity_type_id = feeding_type['id']
        
        generated, skipped = await self._generate_events_for_schedule(schedule)
        return {
            "schedule_id": schedule_id,
            "schedule_name": schedule['schedule_name'],
            "events_generated": generated,
            "events_skipped": skipped
        }

feeding_event_generator = FeedingEventGenerator()
