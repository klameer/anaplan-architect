// The dependency graph (stage 4): Cytoscape with progressive expansion. It starts as one object and its direct
// neighbours and grows one click at a time; nothing is drawn that was not asked for. Line items sit inside their
// module inside the model (compound nodes); arrows follow the data (source -> reader); import and export actions
// attach to the module they touch, dashed, because the exports link them at module level; other models attach to
// the model node as inferred feeds, dashed and amber. A double click opens the node in the evidence drawer.
// Cytoscape is loaded on demand so the rest of the app does not carry it.
import React, { useCallback, useEffect, useRef, useState } from 'react'
import type { Core, ElementDefinition } from 'cytoscape'
import { api, type DepGraphData, type GraphNode } from '../api'
import { useApp } from '../App'

const C = { sky: '#38bdf8', violet: '#a78bfa', ink: '#e8ebe9', muted: '#9aa5a0', amber: '#fbbf24', accent: '#34d399', card: '#141917', rule: '#222a27', soft: '#1c2320' }

const STYLE: any[] = [
  { selector: 'node', style: { label: 'data(label)', 'font-family': 'Geist Mono, Consolas, monospace', 'font-size': 10, color: C.ink, 'text-wrap': 'ellipsis', 'text-max-width': 150,
    'background-color': C.soft, 'border-width': 1, 'border-color': C.rule, width: 'label', height: 20, padding: '6px', shape: 'round-rectangle', 'text-valign': 'center', 'text-halign': 'center' } },
  { selector: 'node.line_item', style: { 'border-color': C.violet, color: C.violet } },
  { selector: 'node.line_item.input', style: { 'background-color': C.card, 'border-style': 'double', 'border-width': 3 } },
  { selector: 'node.line_item.more', style: { 'text-outline-width': 0 } },
  // compound boxes: Cytoscape ignores the alpha of an rgba() fill, so the tint is background-opacity
  { selector: 'node.module', style: { 'border-color': C.sky, color: C.sky, 'background-color': C.sky, 'background-opacity': 0.05, 'text-valign': 'top', 'font-size': 10.5, padding: '14px', 'text-margin-y': -4 } },
  { selector: 'node.model', style: { 'border-color': C.muted, color: C.ink, 'background-color': C.ink, 'background-opacity': 0.02, 'text-valign': 'top', 'font-weight': 500, padding: '20px', 'text-margin-y': -4 } },
  { selector: 'node.model.inferred', style: { 'border-style': 'dashed', 'border-color': C.amber, color: C.amber, 'background-color': C.card, 'background-opacity': 1, 'text-valign': 'center', padding: '8px', height: 22, 'font-weight': 400 } },
  { selector: 'node.action', style: { shape: 'diamond', 'border-color': C.ink, color: C.ink, 'background-color': C.card, width: 'label', height: 24, padding: '12px', 'font-size': 9.5 } },
  { selector: 'node.centre', style: { 'border-width': 2, 'border-color': C.accent } },
  { selector: 'node:selected', style: { 'background-color': C.rule } },
  { selector: 'edge', style: { width: 1.2, 'line-color': C.muted, 'target-arrow-color': C.muted, 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8, 'curve-style': 'bezier', opacity: 0.85 } },
  { selector: 'edge.import, edge.export', style: { 'line-style': 'dashed', 'line-color': C.ink, 'target-arrow-color': C.ink, opacity: 0.55 } },
  { selector: 'edge.feed', style: { 'line-style': 'dashed', 'line-color': C.amber, 'target-arrow-color': C.amber, label: 'data(label)', 'font-size': 9, color: C.amber, 'text-rotation': 'autorotate', 'text-margin-y': -8, 'font-family': 'Geist Mono, Consolas, monospace' } },
]

const ORDER: Record<string, number> = { model: 0, module: 1, line_item: 2, action: 2 }

function elements(d: DepGraphData): ElementDefinition[] {
  const nodes = [...d.nodes].sort((a, b) => ORDER[a.kind] - ORDER[b.kind]).map(n => ({
    group: 'nodes' as const,
    data: { ...n, name: n.name || n.ref, parent: n.parent },
    classes: [n.kind, n.inferred ? 'inferred' : '', n.kind === 'line_item' && !n.calculated ? 'input' : ''].filter(Boolean).join(' '),
  }))
  const edges = d.edges.map(e => ({ group: 'edges' as const, data: { ...e }, classes: [e.type, e.inferred ? 'inferred' : ''].filter(Boolean).join(' ') }))
  return [...nodes, ...edges]
}

function layout(c: Core) {
  c.resize()      // the container may have been measured before the page settled
  c.layout({ name: 'cose', animate: false, fit: true, padding: 24, randomize: false, nodeDimensionsIncludeLabels: true,
    nodeRepulsion: () => 9000, idealEdgeLength: () => 80, edgeElasticity: () => 80, gravity: 0.6, numIter: 600, componentSpacing: 60 } as any).run()
  c.fit(undefined, 24)
}

/** A line item that can still grow shows a plus sign after its name until it is expanded. */
function mark(c: Core) {
  c.nodes('.line_item').forEach(n => {
    const d = n.data() as GraphNode & { name: string }
    const around = (d.uses_count || 0) + (d.used_by_count || 0)
    const present = n.connectedEdges('.ref').length
    const more = !n.hasClass('expanded') && around > present
    n.data('label', more ? `${d.name} +` : d.name)
    n.toggleClass('more', more)
  })
}

export function DepGraph({ eid, model, refName, snapshot }: { eid: string; model: string; refName: string; snapshot: string | null }) {
  const { openEvidence, toast } = useApp()
  const box = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const [ready, setReady] = useState(false)
  const [actions, setActions] = useState(true)
  const [feeds, setFeeds] = useState(true)
  const [count, setCount] = useState({ nodes: 0, edges: 0, truncated: false })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const grow = useCallback(async (m: string, r: string, centre: boolean) => {
    const c = cy.current
    if (!c) return
    setBusy(true)
    try {
      const p = new URLSearchParams({ model: m, ref: r, actions: String(actions), feeds: String(feeds) })
      const d = await api<DepGraphData>(`/api/estates/${eid}/deps/graph?` + p.toString())
      if (cy.current !== c) return
      const fresh = elements(d).filter(el => !c.getElementById(String(el.data.id)).length)
      c.add(fresh)
      const node = c.getElementById(d.centre)
      node.addClass('expanded')
      if (centre) node.addClass('centre')
      mark(c)
      layout(c)
      setCount(s => ({ nodes: c.nodes().filter(n => !n.isParent()).length, edges: c.edges().length, truncated: s.truncated || d.truncated }))
    } finally { setBusy(false) }
  }, [eid, actions, feeds])

  useEffect(() => {
    let live = true
    ;(async () => {
      const cytoscape = (await import('cytoscape')).default
      if (!live || !box.current) return
      const c = cytoscape({ container: box.current, style: STYLE, wheelSensitivity: 0.25, minZoom: 0.15, maxZoom: 3, boxSelectionEnabled: false })
      cy.current = c
      ;(window as any).__cy = c        // for inspection from the console; nothing reads it
      setReady(true)
    })()
    return () => { live = false; cy.current?.destroy(); cy.current = null }
  }, [])

  // the handlers see the latest grow/openEvidence through refs, so they are bound once
  const growRef = useRef(grow); growRef.current = grow
  const openRef = useRef(openEvidence); openRef.current = openEvidence
  useEffect(() => {
    if (!ready || !cy.current) return
    const c = cy.current
    c.on('tap', 'node', evt => {
      const n = evt.target; const d = n.data() as GraphNode
      if ((d.kind === 'line_item' || d.kind === 'module') && !n.hasClass('expanded') && !d.inferred) growRef.current(d.model, d.ref, false).catch((e: any) => toast(e.message))
    })
    c.on('dbltap', 'node', evt => {
      const d = evt.target.data() as GraphNode
      openRef.current({ id: d.id, ref: d.ref, kind: d.kind, model: d.model, snapshot: snapshot || undefined })
    })
    return () => { c.removeListener('tap'); c.removeListener('dbltap') }
  }, [ready, snapshot, toast])

  useEffect(() => {
    if (!ready || !cy.current) return
    cy.current.elements().remove()
    setCount({ nodes: 0, edges: 0, truncated: false }); setErr(null)
    grow(model, refName, true).catch(e => setErr(e.message))
  }, [ready, model, refName, grow])

  return (
    <div className="graph" aria-label="Dependency graph">
      <div className="cy" ref={box} />
      <div className="bar">
        <div className="box">
          <label><input type="checkbox" checked={actions} onChange={e => setActions(e.target.checked)} />actions (module level)</label>
          <label><input type="checkbox" checked={feeds} onChange={e => setFeeds(e.target.checked)} />other models (inferred)</label>
        </div>
        <div className="box">
          <button className="small quiet" onClick={() => cy.current?.fit(undefined, 24)}>Fit</button>
          <button className="small quiet" onClick={() => { if (cy.current) { cy.current.elements().remove(); grow(model, refName, true).catch(e => setErr(e.message)) } }}>Reset</button>
          <span className="muted">{count.nodes} nodes · {count.edges} links{count.truncated ? ' · some neighbours not drawn (over 80)' : ''}{busy ? ' · …' : ''}</span>
        </div>
        <div className="box muted">Click a node with + to grow the graph one step. Double-click opens it as evidence.</div>
        {err && <div className="box warn">{err}</div>}
      </div>
      <div className="legend">
        <span><i className="sw" style={{ borderColor: C.violet }} />line item (double border: input)</span>
        <span><i className="sw" style={{ borderColor: C.sky }} />module</span>
        <span><i className="sw" style={{ borderColor: C.muted }} />model</span>
        <span><i className="sw dia" style={{ borderColor: C.ink }} />action, dashed: module level</span>
        <span><i className="sw" style={{ borderColor: C.amber, borderStyle: 'dashed' }} />other model: inferred from import names</span>
        <span>arrow: data flows into</span>
      </div>
    </div>
  )
}
