CREATE MATERIALIZED VIEW mv_usage_population_stats AS
SELECT
  percentile_cont(0.25) WITHIN GROUP (ORDER BY data_mb)   AS data_p25,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY data_mb)   AS data_p50,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY data_mb)   AS data_p75,
  percentile_cont(0.90) WITHIN GROUP (ORDER BY data_mb)   AS data_p90,
  percentile_cont(0.25) WITHIN GROUP (ORDER BY voice_sec)  AS voice_p25,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY voice_sec)  AS voice_p50,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY voice_sec)  AS voice_p75,
  percentile_cont(0.90) WITHIN GROUP (ORDER BY voice_sec)  AS voice_p90,
  percentile_cont(0.25) WITHIN GROUP (ORDER BY intl_sec)   AS intl_p25,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY intl_sec)   AS intl_p50,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY intl_sec)   AS intl_p75,
  percentile_cont(0.90) WITHIN GROUP (ORDER BY intl_sec)   AS intl_p90,
  COUNT(*) AS subscriber_count
FROM (
  SELECT
    subscriber_id,
    COALESCE(SUM(CASE WHEN cdr_type = 'data'  THEN volume_mb ELSE 0 END), 0)                          AS data_mb,
    COALESCE(SUM(CASE WHEN cdr_type = 'voice' AND NOT roaming THEN duration_seconds ELSE 0 END), 0)   AS voice_sec,
    COALESCE(SUM(CASE WHEN cdr_type = 'voice' AND roaming     THEN duration_seconds ELSE 0 END), 0)   AS intl_sec
  FROM billing_cdr_events
  WHERE start_time >= NOW() - INTERVAL '30 days'
  GROUP BY subscriber_id
) per_sub;
