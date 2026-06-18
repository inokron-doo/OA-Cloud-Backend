from alembic import op
import sqlalchemy as sa


revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade():
    # Distinguish observed (real-time) from predicted (forecast-window) alerts.
    # server_default='observed' classifies every existing row, so the migration
    # is backward compatible and the existing observed save path keeps working.
    op.add_column(
        "alerts",
        sa.Column("origin", sa.String(16), server_default="observed", nullable=False),
    )
    op.add_column("alerts", sa.Column("predicted_for", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("dedupe_key", sa.String(200), nullable=True))
    op.add_column("alerts", sa.Column("cycles_seen", sa.Integer, server_default="1", nullable=False))
    op.add_column(
        "alerts",
        sa.Column(
            "first_seen_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column("alerts", sa.Column("email_sent_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.create_check_constraint(
        "ck_alerts_origin",
        "alerts",
        "origin IN ('observed', 'predicted')",
    )

    # One live predicted row per dedupe_key while active -> enables the
    # ON CONFLICT upsert used by db.upsert_predicted_alert().
    op.create_index(
        "uq_predicted_alert_dedupe",
        "alerts",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("origin = 'predicted' AND status = 'active'"),
    )
    op.create_index("idx_alerts_origin", "alerts", ["origin"])


def downgrade():
    op.drop_index("idx_alerts_origin", table_name="alerts")
    op.drop_index("uq_predicted_alert_dedupe", table_name="alerts")
    op.drop_constraint("ck_alerts_origin", "alerts", type_="check")
    op.drop_column("alerts", "email_sent_at")
    op.drop_column("alerts", "last_seen_at")
    op.drop_column("alerts", "first_seen_at")
    op.drop_column("alerts", "cycles_seen")
    op.drop_column("alerts", "dedupe_key")
    op.drop_column("alerts", "predicted_for")
    op.drop_column("alerts", "origin")
