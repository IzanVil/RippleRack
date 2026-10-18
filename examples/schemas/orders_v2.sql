-- The orders table as the orders-ingest pipeline publishes it from version 2.0.0.
--
--   ripplerack import examples/schemas/orders_v2.sql --from sql --version 2.0.0

CREATE TABLE orders (
    order_id      BIGINT       NOT NULL,
    customer_id   BIGINT       NOT NULL,
    amount_cents  BIGINT       NOT NULL,
    currency      VARCHAR(3)   NOT NULL,
    created_at    TIMESTAMP    NOT NULL,
    coupon_code   VARCHAR(32),
    PRIMARY KEY (order_id)
);

COMMENT ON COLUMN orders.amount_cents IS 'Order total in cents';
