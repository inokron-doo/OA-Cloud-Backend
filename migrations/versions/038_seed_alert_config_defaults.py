from alembic import op


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None

GLOBAL_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


def upgrade():
    # --- Seed per-rule config + global notification routing + new thresholds ---
    # Per-rule config is one JSON object per rule type (avoids key explosion).
    # Resolution reuses db.get_threshold_value (feeding_location -> global -> default).
    op.execute(
        """
        INSERT INTO alert_thresholds (scope_type, scope_id, key, value)
        VALUES
            ('global', '{g}', 'rule_config:low_feed',
                '{{"enabled": true, "severity": "info", "prediction_enabled": true, "prediction_horizon_hours": 24}}'::jsonb),
            ('global', '{g}', 'rule_config:heat_stress',
                '{{"enabled": true, "severity": "warning", "prediction_enabled": true, "prediction_horizon_hours": 48}}'::jsonb),
            ('global', '{g}', 'rule_config:spoilage_risk',
                '{{"enabled": true, "severity": "warning", "prediction_enabled": true, "prediction_horizon_hours": 24}}'::jsonb),
            ('global', '{g}', 'rule_config:missed_feeding',
                '{{"enabled": true, "severity": "warning", "prediction_enabled": false}}'::jsonb),
            ('global', '{g}', 'rule_config:unexpected_feeding',
                '{{"enabled": true, "severity": "info", "prediction_enabled": false}}'::jsonb),
            ('global', '{g}', 'rule_config:cancel_feeding_suggestion',
                '{{"enabled": true, "severity": "info", "prediction_enabled": false}}'::jsonb),
            ('global', '{g}', 'rule_config:low_feed_recurring',
                '{{"enabled": true, "severity": "warning", "prediction_enabled": false}}'::jsonb),
            ('global', '{g}', 'rule_config:health_spike',
                '{{"enabled": true, "severity": "warning", "prediction_enabled": false}}'::jsonb),
            ('global', '{g}', 'notification_routing',
                '{{"critical": "both", "warning": "email", "info": "display"}}'::jsonb),
            ('global', '{g}', 'alert_debounce_cycles', '3'::jsonb),
            ('global', '{g}', 'low_feed_critical_percent', '10'::jsonb),
            ('global', '{g}', 'spoilage_stale_hours', '8'::jsonb),
            ('global', '{g}', 'feed_rise_lookback_minutes', '60'::jsonb),
            ('global', '{g}', 'cancel_feed_high_percent', '80'::jsonb),
            ('global', '{g}', 'cancel_feed_lookahead_hours', '2'::jsonb)
        ON CONFLICT (scope_type, scope_id, key) DO NOTHING
        """.format(g=GLOBAL_SCOPE_ID)
    )

    # --- Threshold cleanup ---
    # Phantom keys (seeded in 019, read by no alert logic) and the unused
    # feed_rise_window_minutes (seeded in 020 but the code reads
    # feed_rise_lookback_minutes). Removed at every scope.
    op.execute(
        """
        DELETE FROM alert_thresholds
        WHERE key IN (
            'feed_deviation_threshold_percent',
            'min_consumption_threshold_kg',
            'feed_analysis_window_days',
            'feed_rise_window_minutes'
        )
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM alert_thresholds
        WHERE scope_type = 'global'
            AND scope_id = '{g}'
            AND key IN (
                'rule_config:low_feed',
                'rule_config:heat_stress',
                'rule_config:spoilage_risk',
                'rule_config:missed_feeding',
                'rule_config:unexpected_feeding',
                'rule_config:cancel_feeding_suggestion',
                'rule_config:low_feed_recurring',
                'rule_config:health_spike',
                'notification_routing',
                'alert_debounce_cycles',
                'low_feed_critical_percent',
                'spoilage_stale_hours',
                'feed_rise_lookback_minutes',
                'cancel_feed_high_percent',
                'cancel_feed_lookahead_hours'
            )
        """.format(g=GLOBAL_SCOPE_ID)
    )

    # Restore the keys removed in upgrade() (original 019/020 defaults).
    op.execute(
        """
        INSERT INTO alert_thresholds (scope_type, scope_id, key, value)
        VALUES
            ('global', '{g}', 'feed_deviation_threshold_percent', '20'::jsonb),
            ('global', '{g}', 'min_consumption_threshold_kg', '10'::jsonb),
            ('global', '{g}', 'feed_analysis_window_days', '7'::jsonb),
            ('global', '{g}', 'feed_rise_window_minutes', '60'::jsonb)
        ON CONFLICT (scope_type, scope_id, key) DO NOTHING
        """.format(g=GLOBAL_SCOPE_ID)
    )
