-- Failed sign-ins, kept so that guessing is slowed: a row per failure, under the name tried (u:<name>) and under the
-- address it came from (a:<address>). Rows older than the window are not counted; a successful sign-in clears the name.
CREATE TABLE login_attempts(
  key TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX login_attempts_key ON login_attempts(key, at);
