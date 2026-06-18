from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004_add_weather_batch_id'
down_revision = '003_migrate_to_django_auth'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add batch_id to weather_observations to group forecast data from same API request.
    Add is_forecast flag to distinguish current vs forecast data.
    """
    
    # Add batch_id column (UUIDs from same forecast request share this)
    op.add_column('weather_observations',
        sa.Column('batch_id', postgresql.UUID(), nullable=True)
    )
    
    # Add is_forecast flag
    op.add_column('weather_observations',
        sa.Column('is_forecast', sa.Boolean(), server_default='false', nullable=False)
    )
    
    # Add barn reference for easier querying
    op.add_column('weather_observations',
        sa.Column('barn_id', postgresql.UUID(), nullable=True)
    )
    
    # Add foreign key to barns
    op.create_foreign_key(
        'weather_observations_barn_id_fkey',
        'weather_observations',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='SET NULL'
    )
    
    # Create indexes for better query performance
    op.create_index('idx_weather_batch_id', 'weather_observations', ['batch_id'])
    op.create_index('idx_weather_is_forecast', 'weather_observations', ['is_forecast'])
    op.create_index('idx_weather_barn_id', 'weather_observations', ['barn_id'])
    op.create_index('idx_weather_obs_time', 'weather_observations', ['obs_time'])


def downgrade():
    """
    Rollback changes
    """
    op.drop_index('idx_weather_obs_time')
    op.drop_index('idx_weather_barn_id')
    op.drop_index('idx_weather_is_forecast')
    op.drop_index('idx_weather_batch_id')
    
    op.drop_constraint('weather_observations_barn_id_fkey', 'weather_observations', type_='foreignkey')
    
    op.drop_column('weather_observations', 'barn_id')
    op.drop_column('weather_observations', 'is_forecast')
    op.drop_column('weather_observations', 'batch_id')
