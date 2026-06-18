"""Alert scheduler.

Thin wrapper that runs the unified AlertEngine on an interval. All alert logic
lives in src/services/rules/ (engine + continuous/event/meta/health/notify).
"""

import os
import logging
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.services.rules.engine import AlertEngine

logger = logging.getLogger(__name__)

ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL_MINUTES", "15"))


class AlertMonitor:
    def __init__(self):
        self.engine = AlertEngine()
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    async def run_all_checks(self):
        try:
            await self.engine.run()
        except Exception as e:
            logger.error(f"Error in alert monitoring: {e}")
            traceback.print_exc()

    def start(self):
        if self.is_running:
            logger.warning("Alert monitor is already running")
            return

        self.scheduler.add_job(
            self.run_all_checks,
            trigger=IntervalTrigger(minutes=ALERT_CHECK_INTERVAL),
            id="alert_monitor_job",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        self.is_running = True
        logger.info(f"Alert monitor started (interval: {ALERT_CHECK_INTERVAL} minutes)")

    def stop(self):
        if not self.is_running:
            return
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        logger.info("Alert monitor stopped")


feed_monitor = AlertMonitor()
