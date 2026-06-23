-- Synthetic SkyLink prepaid plans seed (Story 2.6).
--
-- Inserts 1,000 plans into plans_plans (DDL in V1__baseline_schema.sql:107-122).
-- Idempotent: ON CONFLICT (plan_code) DO NOTHING.
-- Executed by generate_synthetic_data.py, NOT Flyway.
--
-- Categories: SuperData (daily-quota), TalkMore (voice), AllRounder (combo),
--             TextMore (SMS-heavy), Unlimited, SmartValue (budget), International.
-- Validity: 28 / 56 / 84 / 180 / 365 days.
-- Prices: integer paise (paise = Rs × 100), scaled by validity multiplier.
-- NULL quotas = unlimited (data_limit_mb / voice_minutes / sms_count).

WITH dims AS (
    SELECT
        i,
        -- 5 validity options including 6-month and 1-year
        (ARRAY[28, 56, 84, 180, 365])[(i % 5) + 1]       AS validity_days,
        -- 7 plan categories (0..6)
        (i % 7)                                          AS cat,
        -- Fine-grained tier for quota/price variation (0..9)
        ((i / 7) % 10)                                   AS tier
    FROM generate_series(1, 1000) s(i)
),
computed AS (
    SELECT
        i,
        validity_days,
        cat,
        tier,

        -- ── data_limit_mb ──────────────────────────────────────────────────────
        CASE cat
            -- SuperData: daily-quota style; daily_mb × validity_days
            WHEN 0 THEN (
                (ARRAY[100, 500, 1024, 2048, 3072, 5120,
                       100, 500, 1024, 2048])[tier + 1]
                * validity_days
            )::BIGINT
            -- TalkMore: small fixed data pool (100MB–2GB total)
            WHEN 1 THEN ((ARRAY[102400, 204800, 512000, 1048576,
                                102400, 204800, 512000, 1048576,
                                204800, 512000])[tier + 1])::BIGINT
            -- AllRounder: mid fixed data pool (10GB–100GB in MB)
            WHEN 2 THEN ((ARRAY[10240, 20480, 30720, 51200, 76800, 102400,
                                10240, 20480, 30720, 51200])[tier + 1])::BIGINT
            -- TextMore: small fixed data (512MB–5GB)
            WHEN 3 THEN ((ARRAY[512, 1024, 2048, 3072, 5120,
                                512, 1024, 2048, 3072, 5120])[tier + 1])::BIGINT
            -- Unlimited: NULL = unlimited data
            WHEN 4 THEN NULL::BIGINT
            -- SmartValue: tiny fixed data (64MB–640MB)
            WHEN 5 THEN (64 + tier * 64)::BIGINT
            -- International: moderate fixed data (5GB–50GB)
            ELSE (5120 + tier * 5120)::BIGINT
        END AS data_limit_mb,

        -- ── voice_minutes ──────────────────────────────────────────────────────
        CASE
            WHEN cat = 1 AND tier >= 8 THEN NULL::INT   -- TalkMore high tier: unlimited calls
            WHEN cat = 4               THEN NULL::INT   -- Unlimited: unlimited calls
            WHEN cat = 0 THEN (100 + tier *  50)::INT  -- SuperData: limited voice
            WHEN cat = 1 THEN (500 + tier * 300)::INT  -- TalkMore: high voice
            WHEN cat = 2 THEN (200 + tier * 150)::INT  -- AllRounder: moderate
            WHEN cat = 3 THEN (100 + tier *  50)::INT  -- TextMore: basic voice
            WHEN cat = 5 THEN ( 50 + tier *  25)::INT  -- SmartValue: minimal
            ELSE               (200 + tier * 100)::INT  -- International
        END AS voice_minutes,

        -- ── sms_count ──────────────────────────────────────────────────────────
        CASE
            WHEN cat = 3 AND tier >= 7 THEN NULL::INT      -- TextMore high tier: unlimited SMS
            WHEN cat = 4               THEN NULL::INT      -- Unlimited: unlimited SMS
            WHEN cat = 0 THEN (  100 + tier *  20)::INT   -- SuperData
            WHEN cat = 1 THEN (  100 + tier *  50)::INT   -- TalkMore
            WHEN cat = 2 THEN (  200 + tier * 100)::INT   -- AllRounder
            WHEN cat = 3 THEN ( 1000 + tier * 500)::INT   -- TextMore: lots of SMS
            WHEN cat = 5 THEN (   25 + tier *  10)::INT   -- SmartValue
            ELSE               (  100 + tier *  50)::INT  -- International
        END AS sms_count,

        -- ── price_paise ────────────────────────────────────────────────────────
        -- Base × validity multiplier (28d=1×, 56d=1.75×, 84d=2.4×, 180d=4.5×, 365d=8×)
        (
            CASE validity_days
                WHEN  28 THEN 1.00
                WHEN  56 THEN 1.75
                WHEN  84 THEN 2.40
                WHEN 180 THEN 4.50
                ELSE           8.00
            END
            *
            CASE cat
                WHEN 0 THEN (19900 + tier *  3000)::NUMERIC   -- SuperData:    Rs 199–499
                WHEN 1 THEN (14900 + tier *  2000)::NUMERIC   -- TalkMore:     Rs 149–329
                WHEN 2 THEN (24900 + tier *  3000)::NUMERIC   -- AllRounder:   Rs 249–519
                WHEN 3 THEN (14900 + tier *  2000)::NUMERIC   -- TextMore:     Rs 149–329
                WHEN 4 THEN (29900 + tier *  5000)::NUMERIC   -- Unlimited:    Rs 299–799
                WHEN 5 THEN  (4900 + tier *  1000)::NUMERIC   -- SmartValue:   Rs 49–139
                ELSE         (49900 + tier * 20000)::NUMERIC  -- International: Rs 499–2,399
            END
        )::BIGINT AS price_paise

    FROM dims
),
named AS (
    SELECT
        c.*,
        CASE c.cat
            WHEN 0 THEN 'SuperData'
            WHEN 1 THEN 'TalkMore'
            WHEN 2 THEN 'AllRounder'
            WHEN 3 THEN 'TextMore'
            WHEN 4 THEN 'Unlimited'
            WHEN 5 THEN 'SmartValue'
            ELSE        'International'
        END AS cat_label,
        CASE c.cat
            WHEN 0 THEN 'SD'
            WHEN 1 THEN 'TM'
            WHEN 2 THEN 'AR'
            WHEN 3 THEN 'TX'
            WHEN 4 THEN 'UL'
            WHEN 5 THEN 'SV'
            ELSE        'IN'
        END AS cat_code
    FROM computed c
)
INSERT INTO plans_plans (
    id,
    plan_name,
    plan_code,
    price_paise,
    validity_days,
    data_limit_mb,
    voice_minutes,
    sms_count,
    is_active,
    description
)
SELECT
    gen_random_uuid(),

    -- plan_name: "SkyLink SuperData 28D-0001" — unique via i
    'SkyLink ' || cat_label || ' ' || validity_days || 'D-' || LPAD(i::TEXT, 4, '0'),

    -- plan_code: "SKY-SD28-0001" — unique via i
    'SKY-' || cat_code || validity_days || '-' || LPAD(i::TEXT, 4, '0'),

    price_paise,
    validity_days,
    data_limit_mb,
    voice_minutes,
    sms_count,
    TRUE,

    'SkyLink ' || cat_label || ' ' || validity_days || '-day plan. ' ||
    CASE
        WHEN data_limit_mb IS NULL THEN 'Unlimited data'
        WHEN cat = 0 THEN
            (ARRAY[100, 500, 1024, 2048, 3072, 5120,
                   100, 500, 1024, 2048])[tier + 1]::TEXT || 'MB/day data'
        WHEN data_limit_mb >= 1024 THEN (data_limit_mb / 1024)::TEXT || 'GB data'
        ELSE data_limit_mb::TEXT || 'MB data'
    END ||
    ', ' ||
    CASE
        WHEN voice_minutes IS NULL THEN 'unlimited calls'
        ELSE voice_minutes::TEXT || ' voice minutes'
    END ||
    ', ' ||
    CASE
        WHEN sms_count IS NULL THEN 'unlimited SMS'
        ELSE sms_count::TEXT || ' SMS'
    END ||
    CASE cat WHEN 6 THEN '. Includes international roaming and ISD calling.' ELSE '.' END

FROM named
ON CONFLICT (plan_code) DO NOTHING;
