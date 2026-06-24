-- Story 3.7: Add failure_reason to recharge_orders
-- recharge_orders.status can be 'failed'; failure_reason captures why.
-- With FR-14 simulated payment (always succeeds), this column is populated
-- only when a failure path exists (real gateway or future failure-injection).
ALTER TABLE recharge_orders ADD COLUMN failure_reason TEXT NULL;
