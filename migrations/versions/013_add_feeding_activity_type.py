from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '013_add_feeding_activity_type'
down_revision = '012_add_weather_batch_id'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO farm_activities_farmcalendaractivitytype 
        (id, name, description, background_color, border_color, text_color, category)
        VALUES (
            gen_random_uuid(),
            'Feeding',
            'Scheduled feeding activities for livestock',
            '#4CAF50',
            '#388E3C',
            '#FFFFFF',
            'operations'
        )
        ON CONFLICT (name) DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM farm_activities_farmcalendaractivitytype WHERE name = 'Feeding';
    """)
