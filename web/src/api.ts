// The server's JSON, typed loosely where the shape is still moving (stage 1).

export type FileInfo = { uploaded_at: string; original_name: string; bytes: number; problem: string | null }
export type Coverage = {
  files: Record<string, string | null>; snapshot_actions: string; rules_run: string[]; rules_skipped: [string, string][]
  warnings: string[]; missing_columns: string[]; confirmed: string[]; inferred: string[]; missing: string[]
  parse_rate: number; referenced_by_agreement: number | null; unresolved_context?: number
}
export type ModelRow = {
  id: string; name: string; purpose: string; owner: string; aliases: string[]; retired: boolean; seq: number
  files: Record<string, FileInfo>; coverage: Coverage | null; stats: any; module_names?: string[]
  modules?: number; line_items?: number; calculated?: number; cells?: number; parse_rate?: number; patterns?: number; unreferenced?: number
  imports?: number | null; exports?: number | null; stale?: number | null; effort_top10?: number | null; agreement?: number | null
  cells_by_module?: [string, number, number][]; effort_by_module?: [string, number][]     // the ten largest modules: (name, cells, share %) and (name, effort %)
}
export type EdgeState = { state: string; reason: string; by: string | null; when: string | null }
/** A feed between two models, read off the import action names; `state` is the owner's word on it, null while inferred. */
export type Edge = { from: string; to: string; actions: number; targets: string[]; phrases: string[]; state?: EdgeState | null }
export type Question = { kind: string; text: string; why: string }
export type ConvHead = { id: string; title: string; created: string; updated?: string; turns: number; cost_usd: number; snapshot?: string | null; archived?: boolean; scope?: { model?: string; module?: string }
  branched_from?: string | null; branches?: number }
export type NoteObject = { scope: string; model_id?: string | null; model?: string | null; module?: string | null; line_item?: string | null; rule?: string | null }
/** What moved under a note's evidence when the estate went to a new snapshot (stage 5): one row per cited source. */
export type ReviewSource = { id: string; kind: string | null; model: string | null; ref: string | null; name: string | null; snapshot_id: string | null; status: string; was: string | null; now: string | null; detail: string }
export type NoteReview = { snapshot_id: string; at: string; flag: string | null; summary: string; sources: ReviewSource[] }
export type Note = { id: string; estate_id: string; title: string; body: string; type: string; status: string; author_id: string | null; confirmed_by: string | null; confirmed_at: string | null
  created: string; updated: string; superseded_by: string | null; origin_kind: string; origin_conversation_id: string | null; origin_turn_id: string | null
  objects: NoteObject[]; sources: string[]; sources_resolved?: Citation[]; sources_missing?: string[]; scope_labels: string[]; siblings?: { id: string; title: string; type: string; status: string; updated: string; body: string }[]
  review_flag?: string | null; review?: NoteReview | null; reviewed_at?: string | null; reviewed_snapshot_id?: string | null }
export const NOTE_TYPES = ['purpose', 'decision', 'constraint', 'procedure', 'conclusion']
export const NOTE_STATUSES = ['working_assumption', 'user_confirmed', 'superseded']
export type SnapshotHead = { id: string; label: string; created: string; activated_at: string | null; note: string; files: number; run: { id: string; status: string; started: string; finished: string | null; error: string | null } }
export type SnapshotRow = { id: string; estate_id: string; label: string; status: string; created: string; activated_at: string | null; superseded_at: string | null; note: string; file_count: number; model_count: number; run_status: string | null; run_error: string | null
  held_conversations: number; citations: number; deletable: boolean }
export type SnapFile = { snapshot_id: string; model_id: string; model: string; kind: string; blob_sha: string; original_name: string; uploaded_at: string; problem: string | null; bytes: number }
export type ParseRun = { id: string; status: string; started: string; finished: string | null; error: string | null; stats: any; coverage: Record<string, Coverage> | null }
export type Snapshot = { id: string; estate_id: string; label: string; status: string; created: string; activated_at: string | null; superseded_at: string | null; note: string; files: SnapFile[]; run: ParseRun | null; ready: string[]; running?: boolean
  references?: Record<string, number>; deletable?: boolean }
export type Summary = {
  id: string; name: string; created: string; archived: boolean; models: ModelRow[]; snapshot: SnapshotHead | null; snapshots: SnapshotRow[]
  edges: Edge[]; external: Record<string, number>; duplicates: number; questions: Question[]; statuses: number; memories: number
  notes?: number; notes_flagged?: number; documents?: number; tests?: TestsRollup | null
  conversations: ConvHead[]; llm: boolean; provider: string; model: string
}
/** The tests of the catalogue on one snapshot: the rollup travels with the summary, the rows come from /tests. */
export type TestCount = { total: number; found: number; clear: number; not_run: number }
export type TestsRollup = TestCount & { areas: (TestCount & { num: number; key: string; title: string; blurb: string })[] }
export type TestRow = { num: string; key: string; category: number; title: string; what: string; scope: string; status: 'found' | 'clear' | 'not run'; hits: number
  by_model: { model: string; hits: number; cells: number | null; effort: number | null }[]; not_run: { model: string; why: string }[]
  findings: { id: string; title: string; model: string }[]; rules: { ref: string; id: string }[]; needs: string[]; planual: string[] }
export type TestsDetail = TestsRollup & { snapshot: string | null; tests: TestRow[]; note: string }
export type EstateHead = { id: string; name: string; created: string; archived: boolean; models: string[]; documents?: number; chats?: number; notes?: number; snapshot: { id: string; label: string; activated_at: string } | null }

// ---------- citations and verification (stage 3) ----------
export type Citation = { id: string; kind: string; model: string; ref: string; name: string; snapshot_id: string; provenance: string; tool: string; as_written?: string }
export type Figures = { checked: number; traced: number; derived: number; untraced: string[]; benign: number }
/** The verdict recorded on every answer: names sorted, ids checked, figures traced. `clean` when nothing was flagged. */
export type Verification = { mode: string; cited: number; unchecked: number; unverified: number; phantom: string[]; figures: Figures; clean: boolean
  quotes?: { checked: number; found: number; missing: { section: string; quote: string }[] }; why?: { sources: number; not_recorded: boolean; unsupported: boolean } }
export type Turn = { id?: string; q: string; a: string; tools: { tool: string; args: any; cites?: number }[]; unverified: string[]; unchecked?: string[]; citations?: Citation[]
  verification?: Verification | null; usage: any; when: string; by?: string | null
  mode?: 'full' | 'concise'; kind?: string; context?: any; run?: any; blocks?: any[] }
/** A conversation held on a snapshot the estate no longer reads: what the owner must decide before it is answered again (stage 5). */
export type Stale = { held_on: string | null; held: { id: string; label: string; status: string; activated_at: string | null; superseded_at: string | null } | null; active: string; acked: boolean; can_continue: boolean }
export type Conversation = { id: string; estate?: string; title: string; turns: Turn[]; cost_usd?: number; model?: string; snapshot?: string | null; scope?: { model?: string; module?: string }; archived?: boolean; created?: string
  branched_from?: string | null; origin?: { id: string; title: string; snapshot_id: string | null } | null; branches?: { id: string; title: string; snapshot_id: string | null; created: string }[]; stale?: Stale | null }

/** What a chip opens: a citation by id (with enough to look the name up if the id was never recorded), or a name looked up now. */
export type EvidenceTarget = { id?: string | null; ref?: string; model?: string | null; kind?: string; snapshot?: string | null }
export type Ref = { ref: string; id: string | null }
export type ExportRow = { file: string; uploaded_at: string; kind: string; columns: string[]; row: Record<string, string> | null }
export type Evidence = {
  id: string; kind: string; model: string | null; ref: string; name: string; provenance: string; tool: string; estate: string
  snapshot: { id: string; estate_id: string; label: string; status: string; created: string; activated_at: string | null; superseded_at: string | null } | null
  current: boolean; snapshot_fallback: boolean; looked_up_now: boolean; export_row: ExportRow | null
  now: { snapshot_id: string; found: boolean; id: string | null; formula: string | null; changed: boolean } | null
  object: any
  cited_in: { turns: { turn_id: string; seq: number; conversation_id: string; title: string; created: string }[]; notes: { id: string; title: string; status: string; type: string }[] }
}
// ---------- the dependency explorer and the action plan (stage 4) ----------
export type DepHit = { kind: 'line_item' | 'module'; model: string; ref: string; id: string; module: string; module_id: string; name: string; formula: string; calculated: boolean
  cells: number; effort: number | null; uses: number; used_by: number; in: string; line_items?: number }
export type DepSearch = { q: string; hits: DepHit[]; total: number; truncated: boolean }
export type ReachNode = { ref: string; id: string; module: string; module_id: string; name: string; distance: number; cells: number; effort: number | null; calculated: boolean; formula: string
  via: { ref: string; id: string } | null }
export type ReachAction = { ref: string; id: string; action_kind: string; module: string; module_id: string; direction: string; on_selection: boolean; last_run: string; processes: string[] }
export type Reach = {
  selection: { kind: string; model: string; ref: string; id: string; module: string; module_id: string; name: string; formula?: string; cells?: number; line_items?: number }
  direction: 'downstream' | 'upstream'; depth: number | null
  counts: { line_items: number; direct: number; indirect: number; modules: number; models: number; models_inferred: number; actions: number | null; max_distance: number
    footprint_cells: number; by_distance: Record<string, number> }
  modules: { ref: string; id: string; line_items: number; min_distance: number; cells: number }[]
  nodes: ReachNode[]; shown: number
  actions: { level: string; touching: ReachAction[]; unmatched: { ref: string; id: string; action_kind: string; target: string; processes: string[] }[] } | null
  feeds_inferred: { model: string; id: string; actions: number; targets: string[]; phrases: string[]; basis: string; inferred: boolean }[]
  coverage: string[]; limits: string[]; snapshot: string | null
}
export type GraphNode = { id: string; kind: 'model' | 'module' | 'line_item' | 'action'; ref: string; model: string; label: string; parent?: string; module?: string; name?: string
  cells?: number; calculated?: boolean; effort?: number | null; uses_count?: number; used_by_count?: number; formula?: string; line_items?: number
  action_kind?: string; last_run?: string; processes?: string[]; level?: string; inferred?: boolean }
export type GraphEdge = { id: string; source: string; target: string; type: 'ref' | 'import' | 'export' | 'feed'; level?: string; inferred?: boolean; actions?: number; label?: string }
export type DepGraphData = { centre: string; model: string; nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean; snapshot: string | null; edge_types: Record<string, string> }
export type ActionState = { state: string; reason: string; by: string | null; updated: string | null; snapshot_id: string | null; default?: boolean }
export type ObjRef = { ref: string; kind: string | null; model: string; id: string | null }
export type PlanCard = { key: string; state_key: string; kind: 'change' | 'investigation'; title: string; why: string; steps: string[]; done_when: string; role: string; model: string; model_id: string
  objects: string[]; objects_resolved: ObjRef[]; finding_ids: string[]; findings: { id: string; title: string; area: string; strength: string; importance: string; rules: { ref: string; id: string }[] }[]
  strength: string; footprint_cells: number | null; footprint_effort: number | null; notices: string[]; depends_on: string[]
  explorer: { model: string; module: string; name: string | null; ref: string; kind: string } | null; rank_reason: string; worth: boolean; why_not: string; on_plan: boolean; tests: string[]; tests_named?: { num: string; title: string }[]; detail_label?: string
  detail: { object: string; module: string; name: string; effort: number | null; cells: number; formula: string; role?: string }[]; bounded: boolean; footprint_measured: boolean
  state: ActionState; provenance: string }
export type Proposal = { id: string; estate_id: string; snapshot_id: string | null; title: string; why: string; steps: string[]; done_when: string; model: string; model_id: string | null
  objects: string[]; objects_resolved: ObjRef[]; citations: string[]; origin_kind: 'chat_tool' | 'user'; author_id: string | null; conversation_id: string | null; turn_id: string | null
  created: string; withdrawn: boolean; state: ActionState | null; state_key: string; provenance: string }
export type Plan = { actions: PlanCard[]; proposals: Proposal[]; top: number | null; on_plan: number; ranking: string[]; worth: string[]
  considered: number; met_bar: number; none: { message: string; next_check: string } | null; states: string[]; tally: Record<string, number>; unconfirmed: number; snapshot: string | null; limits: string[] }
// ---------- size: dimension inference and cell cost (backlog 18) ----------
export type SizeFactor = { factor: string; kind: 'dim' | 'mod' | 'time' | 'versions'; size: number; evidence: number; agreement: number | null; items: number; assumed: boolean }
export type SizeAxis = { axis: string; kind: 'list' | 'module' | 'time' | 'versions'; size: number | null; size_note: string; items: number; cells: number; marginal: number; unpriced_items: number }
export type SizeItem = { ref: string; id: string; module: string; name: string; cells: number; formula: string; applied: string[]; required: string[]; extra: string[]; implicit: string[]
  judged: boolean; lists_judged: boolean; reason: string; sums: number; constant: boolean; partial: boolean; unplaced: string[]; saved_cells: number | null; price_assumed?: boolean; unpriced: string[]; axis_sizes?: Record<string, number | null>
  key?: string; decision?: ActionState | null }
export type SizeReport = { model: string; model_id: string; snapshot: string; cells: number; has_cells: boolean; line_items: number; calculated: number; inputs: number
  explained: { items: number; of: number; share: number | null }; sizes: SizeFactor[]; axes: SizeAxis[]; over: SizeItem[]; shown: number
  over_summary: { items: number; cells: number; saved: number; priced: number; unpriced: number; partial: number; constant: number; lists_unjudged: number; decided?: number }
  not_judged: Record<string, number>; coverage: string[]; limits: string[] }

export const STATE_LABEL: Record<string, string> = { to_review: 'to review', investigating: 'investigating', done: 'done', keep_current_design: 'keep current design' }
export const STATE_PILL: Record<string, string> = { to_review: 'dim', investigating: 'sky', done: '', keep_current_design: 'violet' }

export const KIND_LABEL: Record<string, string> = { model: 'model', module: 'module', line_item: 'line item', action: 'action', pattern: 'pattern', finding: 'rule', note: 'note', document: 'document passage' }
export const PROV_LABEL: Record<string, string> = { observed: 'observed in the export', user_confirmed: 'confirmed by the owner', inferred: 'inferred', ai_proposed: 'proposed by the architect, unconfirmed', not_established: 'not yet established' }
export const PROV_PILL: Record<string, string> = { observed: 'dim', user_confirmed: '', inferred: 'dim', ai_proposed: 'amber', not_established: 'amber' }

export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, message: string, detail?: any) { super(message); this.status = status; this.detail = detail }
}

export type TraceLevel = 'off' | 'structure' | 'content'
export type Me = { open: boolean; closed: boolean; accounts: boolean; user: { id: string; email: string; name: string; role: string; created: string; last_seen: string | null; disabled: boolean } | null
  tracing?: { enabled: boolean; host: string | null; error: string | null; backend?: string; ceiling?: string; write_only?: boolean }; notice?: string; demo?: boolean
  trace?: { available: boolean; level: TraceLevel; chosen: TraceLevel | null; chosen_at: string | null; default: TraceLevel; ceiling: 'structure' | 'content' }
  workspace: { id: string; name: string; created: string }; data_dir: string; provider: string; model: string; host: string; bind: string; console_hint: string }

/** The readable csrf cookie, sent back as a header on every mutating request (the server compares the two). */
export function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export function withCsrf(opts: RequestInit = {}): RequestInit {
  const method = (opts.method || 'GET').toUpperCase()
  if (method === 'GET' || method === 'HEAD') return opts
  const h = new Headers(opts.headers || {})
  if (!h.has('x-csrf')) h.set('x-csrf', csrf())
  return { ...opts, headers: h }
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(path, withCsrf(opts))
  if (r.status === 401) window.dispatchEvent(new CustomEvent('auth-required'))
  if (!r.ok) {
    let d = ''; let detail: any = undefined
    try { const j = await r.json(); detail = j.detail; d = typeof j.detail === 'string' ? j.detail : (j.detail && typeof j.detail === 'object' && j.detail.message) ? j.detail.message : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new ApiError(r.status, d || r.statusText, detail)
  }
  return r.json()
}

export const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const fmtC = (n?: number | null) => n == null ? '' : n >= 1e9 ? (n / 1e9).toFixed(1) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(0) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : String(n)
export const fmtN = (n?: number | null) => n == null ? '' : n.toLocaleString()
export const fmtB = (n?: number | null) => n == null ? '' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n >= 1e3 ? (n / 1e3).toFixed(0) + ' KB' : n + ' B'
export const fmtUsd = (n?: number | null) => n == null ? '' : (n < 0.01 ? '$' + n.toFixed(4) : '$' + n.toFixed(2))
export const pct = (x?: number | null) => x == null ? '' : (x * 100).toFixed(1) + '%'
export const day = (s?: string | null) => (s || '').slice(0, 10)
export const when = (s?: string | null) => (s || '').slice(0, 16).replace('T', ' ')
export const plain = (t?: string | null) => String(t || '').replace(/`/g, '')
export function ago(s?: string | null): string {
  if (!s) return ''
  const t = new Date(s).getTime(); if (isNaN(t)) return s
  const d = Math.max(0, Date.now() - t), m = Math.floor(d / 60000), h = Math.floor(m / 60), days = Math.floor(h / 24)
  return m < 1 ? 'just now' : m < 60 ? `${m}m ago` : h < 24 ? `${h}h ago` : days < 30 ? `${days}d ago` : `${Math.floor(days / 30)}mo ago`
}
