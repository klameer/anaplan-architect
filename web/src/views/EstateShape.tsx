// The estate at a glance, on Home: where the cells are (a treemap, model then module) and where the calculation
// time goes (effort by module). Both are read off the parse and nothing is inferred: area is the exported cell
// count, a bar is the Calculation Effort column summed by module. A box or a row opens the module; a model's strip
// and its "more modules" box open Size for that model.
import React, { useMemo, useState } from 'react'
import { fmtC, fmtN } from '../api'
import { useApp } from '../App'
import { Obj, barStyle } from '../objects'

type Box = { x: number; y: number; w: number; h: number }
type Leaf = { value: number; name: string; share: number; other: boolean }

/** Squarified treemap (Bruls, Huizing, van Wijk): fills `rect` with one box per item, area proportional to value.
 * A row is laid along the shorter side and closed when one more item would make its boxes less square. Items sorted descending. */
export function squarify<T extends { value: number }>(items: T[], rect: Box): (T & Box)[] {
  const out: (T & Box)[] = []
  const live = items.filter(i => i.value > 0)
  const total = live.reduce((a, i) => a + i.value, 0)
  if (!(total > 0) || rect.w <= 0 || rect.h <= 0) return out
  const scale = (rect.w * rect.h) / total
  let { x, y, w, h } = rect
  let row: T[] = []; let area = 0
  const worst = (r: T[], a: number, side: number) => {
    const max = Math.max(...r.map(i => i.value)) * scale, min = Math.min(...r.map(i => i.value)) * scale
    return Math.max((side * side * max) / (a * a), (a * a) / (side * side * min))
  }
  const close = () => {
    const wide = w >= h                                   // wide space left: the row is a column down its left edge
    const thick = area / (wide ? h : w)
    let off = 0
    for (const i of row) {
      const len = (i.value * scale) / thick
      out.push(wide ? { ...i, x, y: y + off, w: thick, h: len } : { ...i, x: x + off, y, w: len, h: thick })
      off += len
    }
    if (wide) { x += thick; w -= thick } else { y += thick; h -= thick }
    row = []; area = 0
  }
  for (const it of live) {
    const side = Math.min(w, h), a = it.value * scale
    if (row.length && worst([...row, it], area + a, side) > worst(row, area, side)) close()
    row.push(it); area += a
  }
  if (row.length) close()
  return out
}

const W = 1000, H = 380, HEAD = 26                          // the layout space; the page scales it (aspect-ratio on .tmap)
const P = (v: number, of: number) => (100 * v / of) + '%'

export function EstateShape() {
  const { route, summary: s, idx, go, openEvidence } = useApp()
  const [pick, setPick] = useState('')
  const models = useMemo(() => (s?.models || []).filter(m => !m.retired), [s])
  const map = useMemo(() => {
    const sized = models.filter(m => (m.cells || 0) > 0).map(m => ({ value: m.cells || 0, m })).sort((a, b) => b.value - a.value)
    const max = Math.max(1, ...sized.flatMap(x => (x.m.cells_by_module || []).map(c => c[1])))
    return squarify(sized, { x: 0, y: 0, w: W, h: H }).map(mr => {
      const top = (mr.m.cells_by_module || []).filter(c => c[1] > 0)
      const rest = mr.value - top.reduce((a, c) => a + c[1], 0)
      const leaves: Leaf[] = top.map(([name, cells, share]) => ({ value: cells, name, share, other: false }))
      if (rest > 0) leaves.push({ value: rest, name: `${Math.max(1, (mr.m.modules || 0) - top.length)} more modules`, share: Math.round(1000 * rest / mr.value) / 10, other: true })
      leaves.sort((a, b) => b.value - a.value)
      const head = mr.h >= HEAD * 3 && mr.w >= 40 ? HEAD : 0
      return { ...mr, head, max, leaves: squarify(leaves, { x: mr.x, y: mr.y + head, w: mr.w, h: mr.h - head }) }
    })
  }, [models])
  if (!s) return null
  const eid = route.eid!
  const total = map.reduce((a, m) => a + m.value, 0)
  const size = (model: string) => go('#/e/' + eid + '/size/' + encodeURIComponent(model))
  const act = (fn: () => void) => ({ role: 'button' as const, tabIndex: 0, onClick: fn, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } } })
  const withEffort = models.filter(m => (m.effort_by_module || []).length > 0).sort((a, b) => (b.cells || 0) - (a.cells || 0))
  const em = withEffort.find(m => m.name === pick) || withEffort[0]
  const rows = (em?.effort_by_module || []).slice(0, 6)
  const emax = Math.max(0.0001, ...rows.map(r => r[1]))

  return (
    <div className="shape">
      <section>
        <h3>Where the cells are</h3>
        <div className="card">
          {!map.length ? <div className="muted small">No Cell Count column in the Line Items export: sizes are not shown.</div> : <>
            <div className="tmap" role="group" aria-label={`Cells by model and module: ${map.map(m => `${m.m.name} ${fmtC(m.value)}`).join(', ')}`}>
              {map.map(mr => <React.Fragment key={mr.m.id}>
                {mr.head > 0 && <div className="mhead" style={{ left: P(mr.x, W), top: P(mr.y, H), width: P(mr.w, W), height: P(mr.head, H) }}
                  title={`${mr.m.name} · ${fmtN(mr.value)} cells · ${(100 * mr.value / total).toFixed(1)}% of the estate · open Size`} {...act(() => size(mr.m.name))}>{mr.m.name} · {fmtC(mr.value)}</div>}
                {mr.leaves.map(l => <div key={mr.m.id + '::' + l.name} className={'leaf' + (l.other ? ' other' : '') + (l.w >= 300 && l.h >= 150 ? ' big' : '')}
                  style={{ left: P(l.x, W), top: P(l.y, H), width: P(l.w, W), height: P(l.h, H), background: l.other ? undefined : `rgba(56,189,248,${(0.1 + 0.34 * l.value / mr.max).toFixed(3)})` }}
                  title={`${l.other ? l.name + ' in ' + mr.m.name : l.name} · ${fmtN(l.value)} cells · ${l.share}% of ${mr.m.name}`}
                  {...act(() => l.other ? size(mr.m.name) : openEvidence({ ref: l.name, kind: 'module', model: mr.m.name }))}>
                  {l.w >= 84 && l.h >= 30 && <span className="n">{l.name}</span>}
                  {l.w >= 84 && l.h >= 58 && <span className="c">{fmtC(l.value)} · {l.share}%</span>}
                </div>)}
              </React.Fragment>)}
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>{fmtC(total)} cells in {map.length} model{map.length !== 1 ? 's' : ''}. Area is the exported cell count; each model shows its ten largest modules. A box opens the module.</div>
          </>}
        </div>
      </section>
      <section>
        <h3>Where the calculation time goes</h3>
        <div className="card">
          {!em ? <div className="muted small">No Calculation Effort column in the Line Items export: effort is not shown.</div> : <>
            {withEffort.length > 1 && <div className="seg" style={{ marginBottom: 8 }}>{withEffort.map(m => <button key={m.id} className={m.name === em.name ? 'on' : ''} onClick={() => setPick(m.name)}>{m.name}</button>)}</div>}
            <table>
              <thead><tr><th>Module</th><th className="num">Effort</th></tr></thead>
              <tbody>{rows.map(([name, v]) => <tr key={name}><td><Obj text={name} idx={idx} /></td><td className="num bar" style={barStyle(v / emax)}>{v.toFixed(1)}%</td></tr>)}</tbody>
            </table>
            <div className="small muted" style={{ marginTop: 8 }}>Share of {em.name}'s calculation effort, by module{em.effort_top10 != null ? `; ten line items carry ${em.effort_top10}%` : ''}.</div>
          </>}
        </div>
      </section>
    </div>
  )
}
