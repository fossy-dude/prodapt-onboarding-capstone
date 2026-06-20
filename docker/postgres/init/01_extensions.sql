-- Runs as postgres superuser at container creation (once on first volume mount).
-- Extensions must be created before Flyway migrations run as sboai_flyway.
CREATE EXTENSION IF NOT EXISTS "pg_uuidv7";   -- UUIDv7 primary keys on transactional tables
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- AES-256 PII column encryption
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- trigram indexes for MSISDN fuzzy search
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- composite GIN indexes
