from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '011_add_feeding_schedules'
down_revision = '010_add_user_id_farm'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('feeding_schedules',
        sa.Column('id', postgresql.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=True),
        sa.Column('schedule_name', sa.String(255), nullable=False),
        sa.Column('days_of_week', postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column('time_of_day', sa.Time(), nullable=False),
        sa.Column('quantity_kg', sa.Numeric(10, 2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['barn_id'], ['farm_management_farmparcel.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_feeding_schedules_barn', 'feeding_schedules', ['barn_id'])
    op.create_index('idx_feeding_schedules_active', 'feeding_schedules', ['is_active'])
    op.create_index('idx_feeding_schedules_location', 'feeding_schedules', ['feeding_location_id'])


def downgrade():
    op.drop_index('idx_feeding_schedules_location')
    op.drop_index('idx_feeding_schedules_active')
    op.drop_index('idx_feeding_schedules_barn')
    op.drop_table('feeding_schedules')
