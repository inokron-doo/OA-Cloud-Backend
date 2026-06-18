"""Add token_blacklist (another table referenced by code but never migrated).

src/utils/db.py uses token_blacklist for JWT logout (blacklist_token) and the
refresh-token endpoint (is_token_blacklisted), but no migration created it — the
live database had it hand-added. Without it, logout and token refresh fail on a
fresh deployment (normal authenticated requests are unaffected; the per-request
auth path does not consult this table).

Idempotent so it can also be applied to the existing production database safely.
"""
from alembic import op

revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS token_blacklist (
            token          text PRIMARY KEY,
            blacklisted_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS token_blacklist;")
