-- Orac stage 3: what each answer was checked against (names cited / unchecked / unverified, phantom ids, figures traced
-- or untraced). Citation ids on turns were already persisted in 003; this records the verdict beside them.

ALTER TABLE turns ADD COLUMN verification_json TEXT;
