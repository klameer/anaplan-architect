-- Orac stage 5: freshness. A conversation is held on the snapshot it started on; when the estate reads a
-- newer one the owner either continues on the held snapshot (the acknowledgement records which active
-- snapshot it was given against, so the question is asked once per activation) or re-evaluates on the
-- current one as a linked branch (branched_from). Notes are flagged when the evidence they cite moved
-- between snapshots; the review is kept beside the flag, and marking it reviewed records the snapshot the
-- owner reviewed against, which becomes the baseline for the next comparison.

ALTER TABLE conversations ADD COLUMN branched_from TEXT;
ALTER TABLE conversations ADD COLUMN stale_ack_snapshot_id TEXT;

ALTER TABLE notes ADD COLUMN review_flag TEXT;              -- changed | gone | NULL
ALTER TABLE notes ADD COLUMN review_json TEXT;              -- {snapshot_id, at, sources: [{id, kind, model, ref, status, was, now, detail}], flag}
ALTER TABLE notes ADD COLUMN reviewed_at TEXT;
ALTER TABLE notes ADD COLUMN reviewed_by TEXT;
ALTER TABLE notes ADD COLUMN reviewed_snapshot_id TEXT;
