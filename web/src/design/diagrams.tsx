// The design sheet's diagrams: hand-drawn SVG in the app's own tokens (no Mermaid defaults, nothing animates).
// Every label is real text; colour is never the only signal (dashes, labels and counts carry the state too).
import React, { useMemo } from 'react'
import { fmtC, type Reach, type Summary } from '../api'
import { squarify } from '../views/EstateShape'
import { BUILD, BUILD_EDGES, BUILD_EXISTING } from './data'
import { layoutFeeds } from './feedLayout'

const T = { ink: '#e8ebe9', muted: '#9aa5a0', rule: '#222a27', card: '#141917', soft: '#1c2320', accent: '#34d399', sky: '#38bdf8', violet: '#a78bfa', amber: '#fbbf24', bg: '#0e1211' }
const sans = { fontFamily: 'var(--sans)' }, mono = { fontFamily: 'var(--mono)' }

const Arrow = ({ id, color }: { id: string; color: string }) => (
  <marker id={id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1 7 4 1 7" fill="none" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></marker>
)

// ---------- overview: where the cells are ----------
export function Treemap({ s }: { s: Summary }) {
  const W = 1000, H = 360, HEAD = 24
  const map = useMemo(() => {
    const sized = s.models.filter(m => !m.retired && (m.cells || 0) > 0).map(m => ({ value: m.cells || 0, m })).sort((a, b) => b.value - a.value)
    const max = Math.max(1, ...sized.flatMap(x => (x.m.cells_by_module || []).map(c => c[1])))
    return squarify(sized, { x: 0, y: 0, w: W, h: H }).map(mr => {
      const top = (mr.m.cells_by_module || []).filter(c => c[1] > 0)
      const rest = mr.value - top.reduce((a, c) => a + c[1], 0)
      const leaves = top.map(([name, cells, share]) => ({ value: cells, name, share, other: false }))
      if (rest > 0) leaves.push({ value: rest, name: 'other modules', share: Math.round(1000 * rest / mr.value) / 10, other: true })
      leaves.sort((a, b) => b.value - a.value)
      const head = mr.h >= HEAD * 3 && mr.w >= 60 ? HEAD : 0
      return { ...mr, head, max, leaves: squarify(leaves, { x: mr.x, y: mr.y + head, w: mr.w, h: mr.h - head }) }
    })
  }, [s])
  const P = (v: number, of: number) => (100 * v / of) + '%'
  return (
    <div className="ds-tmap" role="img" aria-label={'Cells by model and module: ' + map.map(m => `${m.m.name} ${fmtC(m.value)}`).join(', ')}>
      {map.map(mr => <React.Fragment key={mr.m.id}>
        {mr.head > 0 && <div className="mh" style={{ left: P(mr.x, W), top: P(mr.y, H), width: P(mr.w, W), height: P(mr.head, H) }}><span>{mr.m.name} · {fmtC(mr.value)}</span></div>}
        {mr.leaves.map(l => <div key={mr.m.id + l.name} className={'lf' + (l.w >= 300 && l.h >= 150 ? ' big' : '')} title={`${l.name} · ${fmtC(l.value)} cells · ${l.share}% of ${mr.m.name}`}
          style={{ left: P(l.x, W), top: P(l.y, H), width: P(l.w, W), height: P(l.h, H), background: l.other ? T.soft : `rgba(56,189,248,${(0.08 + 0.36 * l.value / mr.max).toFixed(3)})` }}>
          {l.w >= 90 && l.h >= 30 && <span className="n">{l.name}</span>}
          {l.w >= 90 && l.h >= 56 && <span className="c">{fmtC(l.value)} · {l.share}%</span>}
        </div>)}
      </React.Fragment>)}
    </div>
  )
}

// ---------- overview: how data moves between the models ----------
export function FeedDiagram({ s }: { s: Summary }) {
  const models = s.models.filter(m => !m.retired)
  const stateOf = (e: Summary['edges'][number]) => e.state?.state === 'retired' ? 'retired' : e.state?.state === 'confirmed' ? 'confirmed' : 'inferred'
  const l = useMemo(() => layoutFeeds(models.map(m => m.name), s.edges, i => stateOf(s.edges[i]) === 'retired' ? 54 : Math.max(26, 12 + 7 * String(s.edges[i].actions).length), i => stateOf(s.edges[i]) === 'retired'), [s])
  const edges = l.edges.map(x => ({ ...x, e: s.edges[x.i], st: stateOf(s.edges[x.i]) }))
  const col = (st: string) => st === 'confirmed' ? T.accent : T.muted
  const short = (n: string) => n.length > 25 ? n.slice(0, 24) + '…' : n
  return (
    <div style={{ overflowX: 'auto' }}>
    <svg viewBox={`0 0 ${l.W} ${l.H}`} style={{ display: 'block', margin: '0 auto', width: '100%', maxWidth: l.W, minWidth: Math.min(l.W, 620) }} role="img"
      aria-label={'Feeds between models: ' + (edges.map(x => `${x.e.from} to ${x.e.to}, ${x.e.actions} imports, ${x.st}`).join('; ') || 'none')}>
      <defs><Arrow id="fa-m" color={T.muted} /><Arrow id="fa-a" color={T.accent} /></defs>
      {edges.map(({ e, d, st }) => <path key={e.from + '>' + e.to} d={d} fill="none" stroke={col(st)} opacity={st === 'retired' ? 0.55 : 1} strokeWidth="1.4"
        strokeDasharray={st === 'confirmed' ? undefined : st === 'retired' ? '1.5 5' : '6 4'} strokeLinecap="round" markerEnd={`url(#fa-${st === 'confirmed' ? 'a' : 'm'})`} />)}
      {models.map(m => { const p = l.nodes[m.name]; return <g key={m.id}>
        <rect x={p.x} y={p.y} width={p.w} height={p.h} rx="8" fill={T.card} stroke="#34413c" />
        <text x={p.x + 14} y={p.y + 24} fontSize="13.5" fontWeight="500" fill={T.ink} style={sans}>{short(m.name)}<title>{m.name}</title></text>
        <text x={p.x + 14} y={p.y + 42} fontSize="10.5" fill={T.muted} style={mono}>{m.line_items} line items · {fmtC(m.cells)} cells</text>
      </g> })}
      {edges.map(({ e, label, st }) => <g key={'l' + e.from + '>' + e.to} opacity={st === 'retired' ? 0.75 : 1}>
        <rect x={label.x} y={label.y} width={label.w} height={label.h} rx="4" fill={T.bg} stroke={T.rule} />
        <text x={label.x + label.w / 2} y={label.y + 12.5} textAnchor="middle" fontSize="10.5" fill={st === 'retired' ? T.muted : T.ink} style={mono}>{st === 'retired' ? 'retired' : e.actions}</text>
      </g>)}
    </svg>
    </div>
  )
}

// ---------- build plan: the order to build in (nothing before what it refers to) ----------
export function BuildOrder() {
  const W = 924, H = 322, EW = 188, NW = 172, NH = 46
  const col0 = ['CAL01 Volumes', 'INP01 Volumes', 'INP06 Unit Costs', 'SYS05 FX Rates', 'INP07 Scenario Drivers', 'CAL07 P&L by Cost Centre', 'SYS04 Product Attributes']
  const box: Record<string, { x: number; y: number; w: number; h: number }> = {}
  col0.forEach((n, i) => { box[n] = { x: 10, y: 10 + i * 44, w: EW, h: 32 } })
  box['CAL09 Scenario Planning'] = { x: 290, y: 44, w: NW, h: NH }
  box['CAL13 Scenario Opex'] = { x: 290, y: 170, w: NW, h: NH }
  box['CAL14 Scenario P&L'] = { x: 526, y: 107, w: NW, h: NH }
  box['OUT03 Scenario Comparison'] = { x: 742, y: 107, w: NW, h: NH }
  const step: Record<string, number> = Object.fromEntries(BUILD.map(m => [m.name, m.step]))
  const isNew = (n: string) => !BUILD_EXISTING.includes(n)
  const into: Record<string, number> = {}
  const paths = BUILD_EDGES.map(([f, t]) => {
    const a = box[f], b = box[t], n = BUILD_EDGES.filter(e => e[1] === t).length, i = into[t] = (into[t] ?? -1) + 1
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x - 3, y2 = b.y + b.h / 2 + (i - (n - 1) / 2) * 8
    const lane = t === 'CAL14 Scenario P&L' && a.x < 100 ? (f.startsWith('SYS04') ? 290 : 262) : 0      // a long edge runs under the middle column, never through a box
    const d = lane ? `M${x1},${y1} C${x1 + 40},${y1} ${x1 + 40},${lane} ${x1 + 86},${lane} H476 C506,${lane} 500,${y2} ${x2},${y2}`
      : `M${x1},${y1} C${x1 + (x2 - x1) / 2},${y1} ${x2 - (x2 - x1) / 2},${y2} ${x2},${y2}`
    return { f, t, d, nw: isNew(f) }
  })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={'Build order: ' + BUILD.map(m => `${m.step} ${m.name}`).join(', ')}>
      <defs><Arrow id="bo-m" color={T.muted} /><Arrow id="bo-a" color={T.accent} /></defs>
      {paths.map(p => <path key={p.f + p.t} d={p.d} fill="none" stroke={p.nw ? T.accent : T.muted} strokeOpacity={p.nw ? 0.9 : 0.5} strokeWidth="1.3" markerEnd={`url(#bo-${p.nw ? 'a' : 'm'})`} />)}
      {Object.entries(box).map(([n, b]) => {
        const nw = isNew(n), fill = n === 'CAL09 Scenario Planning', code = n.split(' ')[0], rest = n.slice(code.length + 1)
        if (b.w === EW) return <g key={n}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="6" fill={nw ? T.card : T.bg} stroke={nw ? T.accent : T.rule} strokeDasharray={nw ? undefined : undefined} />
          {nw && <><rect x={b.x + 8} y={b.y + 7} width="18" height="18" rx="4" fill={T.accent} /><text x={b.x + 17} y={b.y + 20} textAnchor="middle" fontSize="10.5" fill="#05140e" style={mono}>{step[n]}</text></>}
          <text x={b.x + (nw ? 33 : 10)} y={b.y + 20} fontSize="10.5" fill={nw ? T.ink : T.muted} style={mono}>{n}</text>
        </g>
        return <g key={n}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="6" fill={T.card} stroke={T.accent} strokeDasharray={fill ? '5 3' : undefined} />
          <rect x={b.x + 8} y={b.y + 7} width="18" height="18" rx="4" fill={T.accent} /><text x={b.x + 17} y={b.y + 20} textAnchor="middle" fontSize="10.5" fill="#05140e" style={mono}>{step[n]}</text>
          <text x={b.x + 33} y={b.y + 19} fontSize="10.5" fill={T.accent} style={mono}>{code}{fill ? ' · empty today' : ''}</text>
          <text x={b.x + 33} y={b.y + 35} fontSize="12" fill={T.ink} style={sans}>{rest}</text>
        </g>
      })}
      <text x="10" y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">ALREADY IN THE MODEL, AND STEP 1</text>
      <text x="290" y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">THEN</text>
      <text x="526" y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">THEN</text>
      <text x="742" y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">LAST</text>
    </svg>
  )
}

// ---------- implications: the reach of a change ----------
type Sector = { ref: string; a0: number; a1: number; n: number; min: number; acts: number }
function sectors(r: Reach): Sector[] {
  const mods = r.modules.slice().sort((a, b) => a.min_distance - b.min_distance || a.ref.localeCompare(b.ref))
  const w = mods.map(m => Math.max(2.2, m.line_items)), tot = w.reduce((a, b) => a + b, 0)
  let a = -Math.PI / 2
  return mods.map((m, i) => { const a0 = a; a += 2 * Math.PI * w[i] / tot
    return { ref: m.ref, a0, a1: a, n: m.line_items, min: m.min_distance, acts: (r.actions?.touching || []).filter(x => x.module === m.ref).length } })
}

/** The selection at the centre, one ring per step away, every line item a dot in its module's sector. */
export function ReachRings({ r }: { r: Reach }) {
  const W = 1000, H = 690, cx = 500, cy = 345, maxD = Math.max(1, r.counts.max_distance)
  const stepR = Math.min(36, 240 / maxD), R = (d: number) => 60 + d * stepR, RM = R(maxD)
  const secs = sectors(r)
  const dots = secs.flatMap(sc => {
    const byD: Record<number, typeof r.nodes> = {}
    for (const n of r.nodes) if (n.module === sc.ref) (byD[n.distance] ||= []).push(n)
    return Object.entries(byD).flatMap(([d, ns]) => ns.map((n, i) => {
      const a = sc.a0 + (sc.a1 - sc.a0) * (i + 1) / (ns.length + 1)
      return { n, x: cx + R(+d) * Math.cos(a), y: cy + R(+d) * Math.sin(a), d: +d }
    }))
  })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Reach of ${r.selection.ref}: ${r.counts.line_items} line items in ${r.counts.modules} modules, up to ${maxD} steps away`}>
      {Array.from({ length: maxD }, (_, i) => i + 1).map(d => <circle key={d} cx={cx} cy={cy} r={R(d)} fill="none" stroke="#2c3632" strokeWidth="1" strokeDasharray={d === 1 ? undefined : '2 4'} />)}
      {secs.map(sc => <line key={sc.ref} x1={cx + 46 * Math.cos(sc.a0)} y1={cy + 46 * Math.sin(sc.a0)} x2={cx + (RM + 8) * Math.cos(sc.a0)} y2={cy + (RM + 8) * Math.sin(sc.a0)} stroke={T.rule} />)}
      {dots.map(({ n, x, y, d }) => <circle key={n.id} cx={x} cy={y} r={d === 1 ? 5.5 : 4.5} fill={T.sky} fillOpacity={d === 1 ? 1 : Math.max(0.35, 0.85 - d * 0.08)} stroke={T.bg} strokeWidth="1.5"><title>{n.ref} · {d} step{d > 1 ? 's' : ''} away, via {n.via?.ref || 'the selection'}</title></circle>)}
      {Array.from({ length: maxD }, (_, i) => i + 1).map(d => <g key={d}><rect x={cx - 8} y={cy - R(d) - 7} width="16" height="14" rx="3" fill={T.bg} /><text x={cx} y={cy - R(d) + 3.5} textAnchor="middle" fontSize="10" fill={T.muted} style={mono}>{d}</text></g>)}
      {secs.map(sc => { const a = (sc.a0 + sc.a1) / 2, c = Math.cos(a), sn = Math.sin(a), x = cx + (RM + 20) * c, y = cy + (RM + 20) * sn
        const anchor = c > 0.25 ? 'start' : c < -0.25 ? 'end' : 'middle', dy = Math.abs(c) <= 0.25 ? (sn > 0 ? 12 : -14) : 0
        return <g key={sc.ref}>
          <text x={x} y={y + dy} textAnchor={anchor} fontSize="12" fill={T.sky} style={mono}>{sc.ref}</text>
          <text x={x} y={y + dy + 15} textAnchor={anchor} fontSize="10.5" fill={T.muted} style={mono}>{sc.n} line item{sc.n > 1 ? 's' : ''} · from step {sc.min}{sc.acts ? ` · ${sc.acts} export` : ''}</text>
        </g> })}
      <rect x={cx - 70} y={cy - 19} width="140" height="38" rx="7" fill={T.card} stroke={T.accent} strokeWidth="1.5" />
      <text x={cx} y={cy - 2} textAnchor="middle" fontSize="12" fill={T.ink} style={mono}>{r.selection.ref}</text>
      <text x={cx} y={cy + 12} textAnchor="middle" fontSize="9.5" fill={T.accent} style={mono} letterSpacing="1.2">THE CHANGE</text>
    </svg>
  )
}

/** The same reach as a grid: a row per module, a column per step away, the count in each cell. */
export function ReachSteps({ r }: { r: Reach }) {
  const maxD = Math.max(1, r.counts.max_distance), secs = sectors(r)
  const LW = 250, CW = Math.min(84, (1000 - LW - 90) / maxD), RH = 34, top = 44, W = 1000, H = top + secs.length * RH + 46
  const count = (m: string, d: number) => r.nodes.filter(n => n.module === m && n.distance === d).length
  const max = Math.max(1, ...secs.flatMap(sc => Array.from({ length: maxD }, (_, i) => count(sc.ref, i + 1))))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Reach of ${r.selection.ref} by module and steps away`}>
      <text x="0" y="16" fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">MODULE</text>
      <text x={LW} y="16" fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">STEPS AWAY FROM {r.selection.ref.toUpperCase()}</text>
      {Array.from({ length: maxD }, (_, i) => <text key={i} x={LW + i * CW + CW / 2 - 4} y="36" textAnchor="middle" fontSize="11" fill={T.muted} style={mono}>{i + 1}</text>)}
      <text x={LW + maxD * CW + 40} y="36" textAnchor="end" fontSize="10" fill={T.muted} style={mono}>TOTAL</text>
      {secs.map((sc, row) => { const y = top + row * RH; return <g key={sc.ref}>
        <line x1="0" x2={W} y1={y} y2={y} stroke={T.rule} />
        <text x="0" y={y + 21} fontSize="12" fill={T.sky} style={mono}>{sc.ref}</text>
        {Array.from({ length: maxD }, (_, i) => { const c = count(sc.ref, i + 1); return c ? <g key={i}>
          <rect x={LW + i * CW} y={y + 5} width={CW - 8} height={RH - 10} rx="4" fill={T.sky} fillOpacity={0.14 + 0.5 * c / max} />
          <text x={LW + i * CW + CW / 2 - 4} y={y + 21} textAnchor="middle" fontSize="12" fill={T.ink} style={mono}>{c}</text>
        </g> : <circle key={i} cx={LW + i * CW + CW / 2 - 4} cy={y + RH / 2} r="1.5" fill={T.rule} /> })}
        <text x={LW + maxD * CW + 40} y={y + 21} textAnchor="end" fontSize="12" fill={T.ink} style={mono}>{sc.n}</text>
      </g> })}
      <line x1="0" x2={W} y1={top + secs.length * RH} y2={top + secs.length * RH} stroke="#34413c" />
      <text x="0" y={top + secs.length * RH + 24} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">LINE ITEMS REACHED</text>
      {Array.from({ length: maxD }, (_, i) => <text key={i} x={LW + i * CW + CW / 2 - 4} y={top + secs.length * RH + 24} textAnchor="middle" fontSize="12" fill={T.muted} style={mono}>{r.counts.by_distance[String(i + 1)] || 0}</text>)}
      <text x={LW + maxD * CW + 40} y={top + secs.length * RH + 24} textAnchor="end" fontSize="12" fill={T.ink} style={mono}>{r.counts.line_items}</text>
    </svg>
  )
}
