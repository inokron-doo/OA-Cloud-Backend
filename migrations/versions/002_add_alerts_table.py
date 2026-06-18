from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_add_alerts_table'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alerts',
        sa.Column('alert_id', postgresql.UUID(), nullable=False),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('barn_name', sa.String(255), nullable=True),
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=True),
        sa.Column('location_name', sa.String(255), nullable=True),
        sa.Column('alert_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(20), server_default='active', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('resolved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('acknowledged_by', postgresql.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['barn_id'], ['barns.barn_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['app_users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('alert_id')
    )
    
    op.create_index('idx_alerts_barn_id', 'alerts', ['barn_id'])
    op.create_index('idx_alerts_status', 'alerts', ['status'])
    op.create_index('idx_alerts_created_at', 'alerts', ['created_at'])
    op.create_index('idx_alerts_type_severity', 'alerts', ['alert_type', 'severity'])
    op.create_index('idx_alerts_feeding_location', 'alerts', ['feeding_location_id'])


def downgrade():
    op.drop_index('idx_alerts_feeding_location')
    op.drop_index('idx_alerts_type_severity')
    op.drop_index('idx_alerts_created_at')
    op.drop_index('idx_alerts_status')
    op.drop_index('idx_alerts_barn_id')
    op.drop_table('alerts')