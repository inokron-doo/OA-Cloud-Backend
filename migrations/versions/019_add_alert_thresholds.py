from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alert_thresholds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", postgresql.UUID(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.CheckConstraint("scope_type IN ('global', 'feeding_location')", name="ck_alert_thresholds_scope_type"),
        sa.UniqueConstraint("scope_type", "scope_id", "key", name="uq_alert_thresholds_scope")
    )

    global_scope_id = "00000000-0000-0000-0000-000000000000"
    op.execute(
        """
        INSERT INTO alert_thresholds (scope_type, scope_id, key, value)
        VALUES
            ('global', '{global_scope_id}', 'heat_stress_thi_threshold', '72'::jsonb),
            ('global', '{global_scope_id}', 'severe_heat_thi_threshold', '80'::jsonb),
            ('global', '{global_scope_id}', 'alert_cooldown_hours', '6'::jsonb),
            ('global', '{global_scope_id}', 'feed_deviation_threshold_percent', '20'::jsonb),
            ('global', '{global_scope_id}', 'min_consumption_threshold_kg', '10'::jsonb),
            ('global', '{global_scope_id}', 'feed_analysis_window_days', '7'::jsonb)
        """.format(global_scope_id=global_scope_id)
    )


def downgrade():
    op.drop_table("alert_thresholds")
