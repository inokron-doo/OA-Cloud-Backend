from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '036'
down_revision = '035'
branch_labels = None
depends_on = None


def upgrade():
    # Replace the single `time_of_day` point with an explicit [time_start, time_end]
    # window. The window the user draws on a schedule (or feeding event) becomes the
    # detection window directly, so the global `feed_rise_window_minutes` tolerance
    # threshold is no longer needed for missed-feeding detection.
    op.add_column('feeding_schedules', sa.Column('time_start', sa.Time(), nullable=True))
    op.add_column('feeding_schedules', sa.Column('time_end', sa.Time(), nullable=True))

    # Backfill: preserve the previous detection behaviour, which used a symmetric
    # +/-60 minute window around `time_of_day`. Postgres time arithmetic wraps
    # within 24h, so near-midnight schedules become cross-midnight ranges
    # (time_end < time_start) which the monitor handles explicitly.
    op.execute(
        """
        UPDATE feeding_schedules
        SET time_start = (time_of_day - interval '60 minutes')::time,
            time_end   = (time_of_day + interval '60 minutes')::time
        WHERE time_of_day IS NOT NULL
        """
    )

    # Any row with a NULL time_of_day (should not exist given the NOT NULL on the
    # old column, but guard anyway) gets a sane default.
    op.execute(
        """
        UPDATE feeding_schedules
        SET time_start = COALESCE(time_start, '00:00:00'::time),
            time_end   = COALESCE(time_end,   '01:00:00'::time)
        """
    )

    op.alter_column('feeding_schedules', 'time_start', nullable=False)
    op.alter_column('feeding_schedules', 'time_end', nullable=False)
    op.drop_column('feeding_schedules', 'time_of_day')

    # The old `feed_rise_window_minutes` threshold was overloaded: it was both the
    # missed-feeding tolerance window (now replaced by the schedule range) and the
    # unexpected-feeding rise lookback. Only the lookback survives, so rename the
    # seeded key (covers global + any per-location overrides) to reflect its single
    # remaining job.
    op.execute(
        """
        UPDATE alert_thresholds
        SET key = 'feed_rise_lookback_minutes'
        WHERE key = 'feed_rise_window_minutes'
        """
    )


def downgrade():
    op.add_column('feeding_schedules', sa.Column('time_of_day', sa.Time(), nullable=True))

    # Recover the original centre point: time_start was centre - 60min.
    op.execute(
        """
        UPDATE feeding_schedules
        SET time_of_day = (time_start + interval '60 minutes')::time
        WHERE time_start IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE feeding_schedules
        SET time_of_day = COALESCE(time_of_day, '07:00:00'::time)
        """
    )
    op.alter_column('feeding_schedules', 'time_of_day', nullable=False)

    op.drop_column('feeding_schedules', 'time_end')
    op.drop_column('feeding_schedules', 'time_start')

    op.execute(
        """
        UPDATE alert_thresholds
        SET key = 'feed_rise_window_minutes'
        WHERE key = 'feed_rise_lookback_minutes'
        """
    )
