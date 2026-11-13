// What was tested, on Home: the catalogue the free report runs (anaplan-estate's numbered tests, in six areas) with
// the result of each on this snapshot. The rollup travels with the summary; the rows of an area are fetched the
// first time one is opened. Found is a review candidate, never a verdict; clear means not found in these exports;
// not run names the export or column the test needs. A rule behind a test opens in the evidence drawer.
import React, { useEffect, useState } from 'react'
import { api, fmtC, fmtN, type TestRow, type TestsDetail } from '../api'
import { useApp } from '../App'
import { CiteChip, Obj } from '../objects'

const PILL: Record<string, string> = { found: 'amber', clear: '', 'not run': 'dim' }

function Where({ r, snapshot }: { r: TestRow; snapshot: string | null }) {
  const { idx } = useApp()
  if (r.status === 'not run') return <span className="small muted">{r.not_run.map(n => `${n.model}: ${n.why}`).join(' · ') || 'not run on these exports'}</span>
  if (r.status === 'clear') return <span className="small muted">nothing found{r.not_run.length ? ` · not run for ${r.not_run.map(n => n.model).join(', ')}` : ''}</span>
  return <span className="small">
    {r.by_model.map(p => <span key={p.model} style={{ display: 'block' }}><Obj text={p.model} idx={idx} /> <span className="muted">{fmtN(p.hits)} hit{p.hits !== 1 ? 's' : ''}{p.cells ? ` · ${fmtC(p.cells)} cells` : ''}{p.effort ? ` · ${p.effort}% of its effort` : ''}</span></span>)}
    {!r.by_model.length && <span className="muted">{fmtN(r.hits)} across the estate</span>}
    {r.rules.length > 0 && <span className="row-chips" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>{r.rules.map(x => <CiteChip key={x.ref} c={{ id: x.id, kind: 'finding', model: '', ref: x.ref, name: x.ref, snapshot_id: snapshot || '', provenance: 'observed', tool: '' }} idx={idx} />)}</span>}
    {r.not_run.length > 0 && <span className="muted" style={{ display: 'block' }}>not run for {r.not_run.map(n => `${n.model} (${n.why})`).join(', ')}</span>}
  </span>
}

export function TestsPanel() {
  const { route, summary: s, toast } = useApp()
  const [open, setOpen] = useState<number | null>(null)
  const [detail, setDetail] = useState<TestsDetail | null>(null)
  const sid = s?.snapshot?.id || null
  useEffect(() => { setDetail(null); setOpen(null) }, [route.eid, sid])          // another estate or snapshot: its own results
  const t = s?.tests
  if (!s || !t) return null
  async function toggle(num: number) {
    setOpen(open === num ? null : num)
    if (!detail) try { setDetail(await api<TestsDetail>(`/api/estates/${route.eid}/tests`)) } catch (e: any) { toast(e.message) }
  }
  const W = (n: number, of: number) => (of ? 100 * n / of : 0) + '%'
  return (
    <section className="tests">
      <h3>What was tested</h3>
      <div className="card scroll">
        <div className="small muted" style={{ marginBottom: 6 }}>{t.total} tests in {t.areas.length} areas, the catalogue the report runs: <b className="ink">{t.found}</b> found something, <b className="ink">{t.clear}</b> came back clear, <b className="ink">{t.not_run}</b> could not be run on these exports. Found is a review candidate, never a verdict.</div>
        <table>
          <thead><tr><th>Area</th><th className="num">Tests</th><th className="num">Found</th><th className="num">Clear</th><th className="num">Not run</th><th style={{ width: '26%' }} /></tr></thead>
          <tbody>{t.areas.map(a => <React.Fragment key={a.num}>
            <tr className="trow" onClick={() => toggle(a.num)} role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(a.num) } }} title={a.blurb}>
              <td><span className="caret">{open === a.num ? '▾' : '▸'}</span>{a.num}. {a.title}</td>
              <td className="num">{a.total}</td><td className="num">{a.found || <span className="muted">0</span>}</td><td className="num">{a.clear || <span className="muted">0</span>}</td><td className="num">{a.not_run || <span className="muted">0</span>}</td>
              <td><div className="tbar" title={`${a.found} found · ${a.clear} clear · ${a.not_run} not run`}><i className="f" style={{ width: W(a.found, a.total) }} /><i className="c" style={{ width: W(a.clear, a.total) }} /><i className="n" style={{ width: W(a.not_run, a.total) }} /></div></td>
            </tr>
            {open === a.num && <tr className="tdetail"><td colSpan={6}>
              <div className="small muted" style={{ margin: '2px 0 6px' }}>{a.blurb}</div>
              {!detail ? <div className="small muted">Reading the results…</div> : <table>
                <tbody>{detail.tests.filter(r => r.category === a.num).map(r => <tr key={r.num}>
                  <td className="num" style={{ width: 44 }}>{r.num}</td>
                  <td style={{ width: '44%' }}>{r.title}<div className="small muted" style={{ whiteSpace: 'normal' }}>{r.what}</div></td>
                  <td style={{ width: 84 }}><span className={'pill ' + PILL[r.status]}>{r.status}</span></td>
                  <td><Where r={r} snapshot={detail.snapshot} /></td>
                </tr>)}</tbody>
              </table>}
            </td></tr>}
          </React.Fragment>)}</tbody>
        </table>
      </div>
    </section>
  )
}
