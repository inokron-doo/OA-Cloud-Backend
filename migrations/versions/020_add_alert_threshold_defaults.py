from alembic import op


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    global_scope_id = "00000000-0000-0000-0000-000000000000"
    op.execute(
        """
        INSERT INTO alert_thresholds (scope_type, scope_id, key, value)
        VALUES
            ('global', '{global_scope_id}', 'feed_stale_minutes', '60'::jsonb),
            ('global', '{global_scope_id}', 'feed_stale_change_percent', '1'::jsonb),
            ('global', '{global_scope_id}', 'low_feed_percent', '20'::jsonb),
            ('global', '{global_scope_id}', 'spoilage_feed_percent', '70'::jsonb),
            ('global', '{global_scope_id}', 'spoilage_temp_c', '25'::jsonb),
            ('global', '{global_scope_id}', 'feed_rise_percent', '5'::jsonb),
            ('global', '{global_scope_id}', 'feed_rise_window_minutes', '60'::jsonb),
            ('global', '{global_scope_id}', 'unexpected_feed_cooldown_minutes', '120'::jsonb),
            ('global', '{global_scope_id}', 'low_feed_recurrence_count', '3'::jsonb),
            ('global', '{global_scope_id}', 'low_feed_recurrence_days', '7'::jsonb),
            ('global', '{global_scope_id}', 'feeding_suggestion_min_kg', '10'::jsonb),
            ('global', '{global_scope_id}', 'heat_stress_duration_minutes', '240'::jsonb),
            ('global', '{global_scope_id}', 'severe_heat_duration_minutes', '360'::jsonb),
            ('global', '{global_scope_id}', 'moohero_alert_cooldown_hours', '6'::jsonb),
            ('global', '{global_scope_id}', 'health_spike_count', '3'::jsonb),
            ('global', '{global_scope_id}', 'health_spike_hours', '24'::jsonb),
            ('global', '{global_scope_id}', 'health_spike_thi_window_hours', '24'::jsonb),
            ('global', '{global_scope_id}', 'health_spike_thi_delta', '8'::jsonb),
            ('global', '{global_scope_id}', 'health_spike_feed_alert_hours', '12'::jsonb)
        ON CONFLICT (scope_type, scope_id, key) DO NOTHING
        """.format(global_scope_id=global_scope_id)
    )


def downgrade():
    global_scope_id = "00000000-0000-0000-0000-000000000000"
    op.execute(
        """
        DELETE FROM alert_thresholds
        WHERE scope_type = 'global'
            AND scope_id = '{global_scope_id}'
            AND key IN (
                'feed_stale_minutes',
                'feed_stale_change_percent',
                'low_feed_percent',
                'spoilage_feed_percent',
                'spoilage_temp_c',
                'feed_rise_percent',
                'feed_rise_window_minutes',
                'unexpected_feed_cooldown_minutes',
                'low_feed_recurrence_count',
                'low_feed_recurrence_days',
                'feeding_suggestion_min_kg',
                'heat_stress_duration_minutes',
                'severe_heat_duration_minutes',
                'moohero_alert_cooldown_hours',
                'health_spike_count',
                'health_spike_hours',
                'health_spike_thi_window_hours',
                'health_spike_thi_delta',
                'health_spike_feed_alert_hours'
            )
        """.format(global_scope_id=global_scope_id)
    )
