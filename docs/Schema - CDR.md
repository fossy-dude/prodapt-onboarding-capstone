Call Detail Records (CDRs) track telecom activity. In India, telecom operators (like Airtel, Jio, or Vi) generate these logs to record metadata for calls, SMS, and data usage. Below are standard JSON examples for each category, formatted to reflect Indian telecom standards (e.g., standard +91 country codes, local bandwidth).

# 1. CDR Schema — Final Recommendation

## 1.1. Design Principles

- **Immutable append-only** — no updates post-write; enrichment lives in side-tables
- **UUIDv7** for all primary keys — time-sortable, globally unique
- **Integer paise** for all costs — no float rounding risk
- **Timezone-aware timestamps** — stored with UTC offset
- **Partitioned by `(timestamp monthly, cdr_type)`** — aligns with TRAI DR cycles

---

## 1.2. Core CDR Table — `cdrs`

All three types share this table. Type-specific nullable columns follow.

| Field            | Type        | Notes                                  |
| ---------------- | ----------- | -------------------------------------- |
| `cdr_id`         | UUIDv7      | PK — unique per CDR record             |
| `session_id`     | UUIDv7      | Links intervals; same across a session |
| `subscriber_id`  | UUID FK     | → subscribers table                    |
| `cdr_type`       | enum        | `voice` \| `sms` \| `data`             |
| `telecom_circle` | varchar     | TRAI-defined circle (e.g., Tamil Nadu) |
| `cell_tower_id`  | varchar     | Serving cell at event start            |
| `roaming`        | bool        | True if on visited network             |
| `cost_paise`     | bigint      | Charge in integer paise                |
| `status`         | enum        | `pending` \| `rated` \| `failed`       |
| `fraud_flag`     | bool        | Set by downstream enrichment           |
| `start_time`     | timestamptz | UTC + offset stored                    |
| `end_time`       | timestamptz | Null for SMS                           |
| `created_at`     | timestamptz | Write time, immutable                  |

---

## 1.3. Voice-Specific Columns *(null for Sms, data)*

| Field              | Type    | Notes                                           |
| ------------------ | ------- | ----------------------------------------------- |
| `from_number`      | varchar | MSISDN E.164 format                             |
| `to_number`        | varchar | MSISDN E.164 format                             |
| `call_direction`   | enum    | `MO` \| `MT`                                    |
| `duration_seconds` | int     | Null until call ends                            |
| `call_status`      | enum    | `answered` \| `no_answer` \| `busy` \| `failed` |

---

## 1.4. SMS-Specific Columns *(null for Voice, data)*

| Field               | Type    | Notes                                |
| ------------------- | ------- | ------------------------------------ |
| `from_number`       | varchar | MSISDN E.164                         |
| `to_number`         | varchar | MSISDN E.164                         |
| `message_direction` | enum    | `MO` \| `MT`                         |
| `sms_status`        | enum    | `delivered` \| `failed` \| `pending` |

*Flat billing — no encoding_type or segment count.*

---

## 1.5. Data-Specific Columns + TRAI Fields *(null for Voice, sms)*

| Field           | Type          | Notes                                           |
| --------------- | ------------- | ----------------------------------------------- |
| `network_type`  | enum          | `2G` \| `3G` \| `4G` \| `5G`                    |
| `downloaded_mb` | numeric(10,3) | Per interval                                    |
| `uploaded_mb`   | numeric(10,3) | Per interval                                    |
| `volume_mb`     | numeric(10,3) | Derived: down + up; store for query convenience |
| `apn`           | varchar       | TRAI-required — Access Point Name               |
| `imei`          | varchar       | TRAI-required — device identifier               |
| `operator_id`   | varchar       | TRAI-required — operator code                   |

---

## 1.6. Enrichment Side-Table — `cdr_enrichments`

Keeps the core CDR immutable while allowing rating and fraud updates.

| Field             | Type         | Notes                          |
| ----------------- | ------------ | ------------------------------ |
| `enrichment_id`   | UUIDv7       | PK                             |
| `cdr_id`          | UUID FK      | → cdrs.cdr_id                  |
| `enrichment_type` | enum         | `rating` \| `fraud`            |
| `previous_status` | enum         | Snapshot before enrichment     |
| `new_status`      | enum         | Post-enrichment value          |
| `fraud_score`     | numeric(5,4) | 0.0–1.0; null if type = rating |
| `enriched_by`     | varchar      | System/service identifier      |
| `enriched_at`     | timestamptz  | Write time                     |

---

## 1.7. MVP Baseline

If standing this up immediately with minimal complexity — **single table, no side-table yet**:

- Ship `cdrs` with all columns above
- Add `fraud_flag bool` and `rated_at timestamptz` directly on the row as nullable
- Migrate to the enrichment side-table when re-rating or audit trail becomes a hard requirement