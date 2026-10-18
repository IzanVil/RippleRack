-- Columns that have no RippleRack type: an error, or a json field with --lenient.
CREATE TABLE places (
    id        bigint NOT NULL,
    location  geometry(Point, 4326),
    open_days int4range NOT NULL,
    label     text
);
