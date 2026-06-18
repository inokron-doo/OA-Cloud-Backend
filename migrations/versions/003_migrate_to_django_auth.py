from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_migrate_to_django_auth'
down_revision = '002_add_alerts_table'
branch_labels = None
depends_on = None


def upgrade():
    """
    Migrate from app_users to Django's auth_user table.
    This migration:
    1. Drops the old app_users table (no longer used)
    2. Updates alerts table foreign key to reference auth_user.id
    """
    
    # Drop the foreign key constraint on alerts.acknowledged_by
    op.drop_constraint('alerts_acknowledged_by_fkey', 'alerts', type_='foreignkey')
    
    # Recreate the foreign key to point to auth_user.id (INTEGER) instead of app_users.user_id (UUID)
    # First, change the column type from UUID to INTEGER
    op.execute("ALTER TABLE alerts ALTER COLUMN acknowledged_by TYPE INTEGER USING NULL")
    
    # Add the new foreign key constraint to auth_user
    op.create_foreign_key(
        'alerts_acknowledged_by_fkey',
        'alerts',
        'auth_user',
        ['acknowledged_by'],
        ['id'],
        ondelete='SET NULL'
    )
    
    # Drop the unused app_users table
    op.drop_table('app_users')


def downgrade():
    """
    Rollback to app_users table.
    WARNING: This will lose data if you've created users in auth_user!
    """
    
    # Recreate app_users table
    op.create_table('app_users',
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column('email', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # Drop the auth_user foreign key
    op.drop_constraint('alerts_acknowledged_by_fkey', 'alerts', type_='foreignkey')
    
    # Change acknowledged_by back to UUID
    op.execute("ALTER TABLE alerts ALTER COLUMN acknowledged_by TYPE UUID USING NULL")
    
    # Recreate the old foreign key to app_users
    op.create_foreign_key(
        'alerts_acknowledged_by_fkey',
        'alerts',
        'app_users',
        ['acknowledged_by'],
        ['user_id'],
        ondelete='SET NULL'
    )