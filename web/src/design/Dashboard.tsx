// The workspace dashboard: the estate at a glance. A dashboard, not a wall: the model map, what was tested and where
// the cells are first; then, inside one model, who reads whom, where the calculation time goes, the functions it leans
// on and its longest formulas; then what the modules are for. Everything is read off the parse (the line-item index and
// the exports). A panel whose export column is missing says so. Every panel can ask the chat about itself.
import React, { useEffect, useState } from 'react'
import { api, fmtC, type Summary, type TestsDetail } from '../api'
import { FeedDiagram, Treemap } from './diagrams'

type Profile = { model: string; modules: { name: string; area: string; line_items: number }[]; has_areas: boolean; edges: [string, string, number][]
  functions: { fn: string; kind: string; n: number; cells: number; most_in: string | null }[]; longest: { ref: string; formula_len: number; ifs: number; depth: number; cells: number }[] }
const T = { ink: '#e8ebe9', muted: '#9aa5a0', rule: '#222a27', sky: '#38bdf8', accent: '#34d399', bg: '#0e1211' }
const ROLES: [string, string, string][] = [['data', 'data', '#38bdf8'], ['input', 'inputs', '#a78bfa'], ['system', 'system', '#9aa5a0'], ['calc', 'calculation', '#34d399'], ['output', 'output', '#fbbf24'], ['report', 'output', '#fbbf24'], ['', 'not stated', '#4a5651']]
const roleOf = (area: string) => { const a = (area || '').toLowerCase(); const r = ROLES.find(x => x[0] && a.startsWith(x[0])); return r ? r[1] : 'not stated' }
const roleColour = (r: string) => ROLES.find(x => x[1] === r)![2]
const ORDER = ['data', 'inputs', 'system', 'calculation', 'output', 'not stated']

const AskCtx = React.createContext<((q: string) => void) | null>(null)
const Panel = ({ k, note, ask, children, cap }: { k: string; note?: string; ask?: string; children: React.ReactNode; cap?: React.ReactNode }) => { const onAsk = React.useContext(AskCtx); return (
  <div className="ds-fig"><div className="fh"><span className="k">{k}</span>{note && <span className="mono dim" style={{ fontSize: 10.5 }}>{note}</span>}<span className="grow" />{ask && onAsk && <button className="ds-tag" style={{ background: 'transparent', cursor: 'pointer' }} onClick={() => onAsk(ask.charAt(0).toUpperCase() + ask.slice(1))} title={'Ask: ' + ask}>ask →</button>}</div>
    <div className="fb">{children}</div>{cap && <div className="cap">{cap}</div>}</div>
) }

/** Module by module: a filled cell means the row's module reads the column's; the shade is how many of its line items do. */
function Matrix({ p }: { p: Profile }) {
  const ms = p.modules.slice().sort((a, b) => ORDER.indexOf(roleOf(a.area)) - ORDER.indexOf(roleOf(b.area)) || a.name.localeCompare(b.name))
  const at = new Map(ms.map((m, i) => [m.name, i]))
  const n = ms.length, C = Math.min(18, 520 / Math.max(1, n)), L = 196, TOP = 172, W = L + n * C + 44, H = TOP + n * C + 26
  const grid = ms.map(() => ms.map(() => 0))
  for (const [f, t, k] of p.edges) { const i = at.get(f), j = at.get(t); if (i != null && j != null) grid[i][j] = k }
  const max = Math.max(1, ...grid.flat()), readBy = ms.map((_, j) => grid.filter(r => r[j] > 0).length)
  const top = ms.map((m, j) => ({ m, v: readBy[j] })).sort((a, b) => b.v - a.v)[0]
  if (!n) return <div className="dim">This model has no modules.</div>
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Module dependency matrix, ${n} modules; most read: ${top?.m.name}, by ${top?.v} modules`} style={{ maxWidth: W }}>
      {ms.map((m, i) => <g key={m.name}>
        <text x={L - 8} y={TOP + i * C + C * 0.72} textAnchor="end" fontSize="10" fill={T.muted} style={{ fontFamily: 'var(--mono)' }}>{m.name.length > 30 ? m.name.slice(0, 29) + '…' : m.name}</text>
        <text transform={`translate(${L + i * C + C * 0.7},${TOP - 6}) rotate(-58)`} fontSize="10" fill={T.muted} style={{ fontFamily: 'var(--mono)' }}>{m.name.length > 26 ? m.name.slice(0, 25) + '…' : m.name}</text>
        <rect x={L - 5} y={TOP + i * C + 1} width="3" height={C - 2} fill={roleColour(roleOf(m.area))} />
        {ms.map((b, j) => { const v = grid[i][j]; return <rect key={b.name} x={L + j * C + 1} y={TOP + i * C + 1} width={C - 2} height={C - 2} rx="2" fill={i === j ? 'transparent' : v ? T.sky : '#141917'} fillOpacity={v ? 0.25 + 0.75 * v / max : 1}>{v > 0 && <title>{m.name} reads {b.name}: {v} line item{v > 1 ? 's' : ''}</title>}</rect> })}
        <text x={L + n * C + 8} y={TOP + i * C + C * 0.72} fontSize="9.5" fill={T.muted} style={{ fontFamily: 'var(--mono)' }}>{grid[i].filter(v => v > 0).length || ''}</text>
        <text x={L + i * C + C / 2} y={TOP + n * C + 13} textAnchor="middle" fontSize="9.5" fill={readBy[i] >= 5 ? T.ink : T.muted} style={{ fontFamily: 'var(--mono)' }}>{readBy[i] || ''}</text>
      </g>)}
      <text x={L - 8} y={TOP + n * C + 13} textAnchor="end" fontSize="9" fill={T.muted} style={{ fontFamily: 'var(--mono)' }} letterSpacing="1.2">READ BY</text>
      <text x={L + n * C + 8} y={TOP - 6} fontSize="9" fill={T.muted} style={{ fontFamily: 'var(--mono)' }} letterSpacing="1.2">READS</text>
    </svg>
  )
}

function Roles({ ps, models }: { ps: Record<string, Profile>; models: string[] }) {
  const used = new Set<string>()
  const rows = models.map(name => { const p = ps[name]; const ms = p?.modules || []
    return <div key={name} className="rw">
      <div className="l"><span>{name}</span><span className="mono dim">{ms.length} modules</span></div>
      {p && !p.has_areas ? <div className="ds-gap" style={{ margin: 0 }}>No Modules export with a Functional Area column for this model: roles are not shown.</div>
        : <div className="b">{ORDER.map(r => { const k = ms.filter(m => roleOf(m.area) === r).length; if (k) used.add(r); return k ? <i key={r} style={{ flex: k, background: roleColour(r) }} title={`${k} ${r}`}>{k}</i> : null })}</div>}
    </div> })
  return <div className="ds-roles">{rows}<div className="ds-bk" style={{ marginTop: 10 }}>{ORDER.filter(r => used.has(r)).map(r => <span key={r}><u style={{ background: roleColour(r) }} />{r}</span>)}</div></div>
}

export function Dashboard({ s, onAsk, bare }: { s: Summary; onAsk?: (q: string) => void; bare?: boolean }) {
  const [ps, setPs] = useState<Record<string, Profile>>({})
  const [tests, setTests] = useState<TestsDetail | null>(null)
  const [pick0, setPick] = useState('')
  const pick = pick0 || s.models.slice().sort((a, b) => (b.cells || 0) - (a.cells || 0))[0]?.name || ''
  useEffect(() => {
    let off = false
    setPs({})
    for (const m of s.models) api<Profile>(`/api/estates/${s.id}/profile?model=${encodeURIComponent(m.name)}`).then(p => { if (!off) setPs(x => ({ ...x, [m.name]: p })) }).catch(() => {})
    api<TestsDetail>('/api/estates/' + s.id + '/tests').then(t => { if (!off) setTests(t) }).catch(() => {})
    return () => { off = true }
  }, [s.id, s.snapshot?.id])
  const li = s.models.reduce((a, m) => a + (m.line_items || 0), 0), cells = s.models.reduce((a, m) => a + (m.cells || 0), 0), nm = s.models.reduce((a, m) => a + (m.modules || 0), 0)
  const em = s.models.find(m => m.name === pick), eff = (em?.effort_by_module || []).slice(0, 7), emax = Math.max(0.001, ...eff.map(e => e[1]))
  const p = ps[pick], fmax = Math.max(1, ...(p?.functions || []).map(f => f.n))
  return <AskCtx.Provider value={onAsk || null}>
    {!bare && <><div className="ds-kick"><span className="type">Workspace</span><span className="k">· the estate at a glance · read {s.snapshot?.activated_at?.slice(0, 10)}</span></div>
      <h1 className="ds-q">{s.name}</h1></>}
    <div className="ds-tiles"><div><div className="v">{s.models.length}</div><div className="l">models</div></div><div><div className="v">{nm}</div><div className="l">modules</div></div><div><div className="v">{li.toLocaleString()}</div><div className="l">line items</div></div><div><div className="v">{fmtC(cells)}</div><div className="l">cells</div></div><div><div className="v">{s.tests?.found} <span className="dim" style={{ fontSize: 13 }}>/ {s.tests?.total}</span></div><div className="l">tests found something</div></div></div>

    <div className="ds-dash a">
      <Panel k="Model map" note="feeds read off import names" ask="how does data move between the models?" cap="Solid: confirmed by the owner. Dashed: inferred. The number is the count of imports.">
        {s.models.length > 1 || s.edges.length ? <FeedDiagram s={s} /> : <div className="dim">One model, no feeds to draw.</div>}</Panel>
      <Panel k="What was tested" note={`${s.tests?.total ?? 0} tests`} ask="what did you test, and what came back clear?">
        <div className="ds-tests">{(tests?.areas || s.tests?.areas || []).map(a => <div key={a.num} className="tr"><div className="l"><span>{a.title}</span><span className="mono dim">{a.found} of {a.total}</span></div>
          <div className="b"><i style={{ flex: a.found, background: '#fbbf24' }} /><i style={{ flex: a.clear, background: '#34d399' }} /><i style={{ flex: a.not_run, background: '#4a5651' }} /></div></div>)}
          <div className="ds-bk" style={{ marginTop: 10 }}><span><u style={{ background: '#fbbf24' }} />found something</span><span><u style={{ background: '#34d399' }} />clear</span><span><u style={{ background: '#4a5651' }} />not run</span></div></div>
      </Panel>
    </div>
    <div style={{ height: 14 }} />
    <Panel k="Where the cells are" note="area = exported cell count" ask="why is the estate the size it is?">{cells > 0 ? <Treemap s={s} /> : <div className="ds-gap" style={{ margin: 0 }}>No Cell Count column in the Line Items exports: sizes are not shown.</div>}</Panel>

    <div className="ds-sec"><span className="k">Inside a model</span><div className="ds-seg" role="group" aria-label="Model">{s.models.map(m => <button key={m.id} className={m.name === pick ? 'on' : ''} onClick={() => setPick(m.name)}>{m.name}</button>)}</div></div>
    <div className="ds-dash b">
      <Panel k="Who reads whom" note="module by module" ask={`which modules in ${pick} are the hubs?`} cap="A filled cell: the row's module reads the column's. Darker: more of its line items do. A full column is a hub. Read off the references the grammar found in every formula.">
        {!p ? <div className="dim">Reading the index…</div> : <Matrix p={p} />}</Panel>
      <div>
        <Panel k="Where the calculation time goes" note="share of the model's effort" ask={`what carries the calculation effort in ${pick}?`}>
          {eff.length ? <table><tbody>{eff.map(([n, v]) => <tr key={n}><td><span className="ds-chip mod">{n}</span></td><td className="num barcell" style={{ width: '40%' }}>{v.toFixed(1)}%<i style={{ width: 100 * v / emax + '%', background: '#a78bfa' }} /></td></tr>)}</tbody></table>
            : <div className="ds-gap" style={{ margin: 0 }}>No Calculation Effort column in this model's Line Items export: effort is not shown.</div>}</Panel>
        <div style={{ height: 14 }} />
        <Panel k="Functions it leans on" note="line items using each" ask={`where are the expensive functions in ${pick}?`}>
          {!p ? <div className="dim">Reading…</div> : <table><thead><tr><th>Function</th><th className="num">Line items</th><th>Most in</th></tr></thead>
            <tbody>{p.functions.slice(0, 9).map(r => <tr key={r.fn + r.kind}><td><span className="ds-f"><span className="fn">{r.fn}</span>{r.kind === 'clause' && <span className="dim">:</span>}</span></td><td className="num barcell" style={{ width: '34%' }}>{r.n}<i style={{ width: 100 * r.n / fmax + '%', background: '#fbbf24' }} /></td><td>{r.most_in && <span className="ds-chip mod">{r.most_in}</span>}</td></tr>)}</tbody></table>}</Panel>
        <div style={{ height: 14 }} />
        <Panel k="Longest formulas" note="characters · IFs · nesting" ask={`which formulas in ${pick} are hardest to maintain?`}>
          {!p ? <div className="dim">Reading…</div> : <table><tbody>{p.longest.map(r => { const i = r.ref.indexOf('.'); return <tr key={r.ref}><td><span className="ds-chip li"><s>{r.ref.slice(0, i)}</s><em>.</em>{r.ref.slice(i + 1)}</span></td><td className="num">{r.formula_len.toLocaleString()} · {r.ifs} · {r.depth}</td></tr> })}</tbody></table>}</Panel>
      </div>
    </div>
    <div style={{ height: 14 }} />
    <Panel k="What the modules are for" note="from the Functional Area column" ask="which modules are inputs and which are outputs?" cap="Read off the Modules export. A module with no functional area is shown as not stated, never guessed from its name.">
      <Roles ps={ps} models={s.models.map(m => m.name)} /></Panel>
  </AskCtx.Provider>
}
