-- 007: tracing. A conversation is one trace in the trace store; the root span created on its first turn is remembered
-- here (trace id, root span id, host) so every later turn attaches under it, across server restarts.
ALTER TABLE conversations ADD COLUMN trace_json TEXT;
