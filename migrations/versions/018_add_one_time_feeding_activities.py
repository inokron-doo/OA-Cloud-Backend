from alembic import op
import sqlalchemy as sa


revision = '018'
down_revision = '017_add_moohero_sync_log'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE feeding_schedules
        ADD COLUMN farm_calendar_activity_id UUID,
        ADD COLUMN actual_feed_datetime TIMESTAMP WITH TIME ZONE
    """)
    
    op.execute("""
        CREATE INDEX idx_feeding_schedules_calendar_activity 
        ON feeding_schedules(farm_calendar_activity_id) 
        WHERE farm_calendar_activity_id IS NOT NULL
    """)
    
    op.execute("""
        CREATE INDEX idx_feeding_schedules_actual_datetime 
        ON feeding_schedules(actual_feed_datetime) 
        WHERE actual_feed_datetime IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_feeding_schedules_actual_datetime")
    op.execute("DROP INDEX IF EXISTS idx_feeding_schedules_calendar_activity")
    op.execute("""
        ALTER TABLE feeding_schedules
        DROP COLUMN actual_feed_datetime,
        DROP COLUMN farm_calendar_activity_id
    """)
