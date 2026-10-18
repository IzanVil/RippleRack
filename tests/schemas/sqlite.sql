-- Written by hand for SQLite, which lets a column go without a type.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS "events" (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  name    TEXT NOT NULL,
  price   REAL,
  data    BLOB,
  at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  flag    BOOLEAN,
  payload JSON,
  legacy
);

CREATE INDEX idx_events_name ON events (name);
