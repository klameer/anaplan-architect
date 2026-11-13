// The model map's layout: a layered drawing (models in columns, feeds running left to right) in which a card never sits
// on another card and an edge label never sits on a card. Pure: names and edges in, boxes and paths out, so it is tested
// without a browser (feedLayout.test.ts).
//
// 1. feeds that would close a loop (A feeds B and B feeds A) are turned round for the layout only, and drawn with their
//    arrow at the true target; 2. each model's column is the longest chain of feeds that reaches it; 3. a feed that skips
//    a column gets a slot in each column it crosses, so it runs through a gap, never through a card; 4. columns are
//    ordered to keep feeds short; 5. every size comes from the card size, and the drawing is as large as its content.
export type FEdge = { from: string; to: string }
export type Box = { x: number; y: number; w: number; h: number }
export type LaidEdge = { i: number; d: string; label: Box; reversed: boolean }
export type Laid = { W: number; H: number; nodes: Record<string, Box>; edges: LaidEdge[] }

export const NW = 196, NH = 58
const PAD = 14, GAPX = 150, GAPY = 26, SLOT = 22, LABEL_H = 18, LABEL_GAP = 4

type Item = { key: string; node?: string; h: number; y: number; order: number; left: Item[]; right: Item[] }

export function layoutFeeds(all: string[], edges: FEdge[], labelW: (i: number) => number = () => 26, weak: (i: number) => boolean = () => false): Laid {
  const has = new Set(all)
  const fed = new Set(edges.filter(e => has.has(e.from) && has.has(e.to) && e.from !== e.to).flatMap(e => [e.from, e.to]))
  const names = all.filter(n => fed.has(n)), alone = all.filter(n => !fed.has(n))      // models with no feed at all go in rows underneath
  const use = edges.map((e, i) => ({ ...e, i })).filter(e => has.has(e.from) && has.has(e.to) && e.from !== e.to)

  // 1. loops: a depth-first walk from the models nothing feeds; a feed back to a model still on the walk is turned round.
  //    A weak feed (one that no longer runs) does not shape the drawing: the live feeds are placed first, and a weak one
  //    then runs whichever way the live ones left its two ends.
  const strong = use.filter(e => !weak(e.i)), soft = use.filter(e => weak(e.i))
  const out: Record<string, typeof use> = {}
  for (const n of names) out[n] = []
  for (const e of strong) out[e.from].push(e)
  const fedBy = new Set(strong.map(e => e.to))
  const state: Record<string, number> = {}, turned = new Set<number>()
  const walk = (n: string) => {
    state[n] = 1
    for (const e of out[n]) { if (state[e.to] === 1) turned.add(e.i); else if (!state[e.to]) walk(e.to) }
    state[n] = 2
  }
  for (const n of [...names.filter(n => !fedBy.has(n)), ...names]) if (!state[n]) walk(n)
  const first: Record<string, number> = {}
  for (const n of names) first[n] = 0
  const strongDir = strong.map(e => turned.has(e.i) ? { a: e.to, b: e.from } : { a: e.from, b: e.to })
  for (let pass = 0; pass < names.length; pass++) for (const e of strongDir) if (first[e.b] < first[e.a] + 1) first[e.b] = first[e.a] + 1
  for (const e of soft) if (first[e.to] < first[e.from]) turned.add(e.i)          // a weak feed against the live order is drawn against it
  const dir = use.map(e => turned.has(e.i) ? { a: e.to, b: e.from, i: e.i, rev: true } : { a: e.from, b: e.to, i: e.i, rev: false })

  // 2. columns: the longest chain that reaches a model; a model nothing feeds sits just left of what it feeds
  const layer: Record<string, number> = {}
  for (const n of names) layer[n] = 0
  for (let pass = 0; pass < names.length; pass++) for (const e of dir) if (layer[e.b] < layer[e.a] + 1) layer[e.b] = layer[e.a] + 1
  for (const n of names) {
    const outs = dir.filter(e => e.a === n)
    if (outs.length && !dir.some(e => e.b === n)) layer[n] = Math.min(...outs.map(e => layer[e.b])) - 1
  }
  const nL = Math.max(0, ...names.map(n => layer[n])) + 1

  // 3. slots for feeds that cross a column
  const cols: Item[][] = Array.from({ length: nL }, () => [])
  const item: Record<string, Item> = {}
  for (const n of names) { const it: Item = { key: n, node: n, h: NH, y: 0, order: cols[layer[n]].length, left: [], right: [] }; item[n] = it; cols[layer[n]].push(it) }
  const chains = dir.map(e => {
    const chain: Item[] = [item[e.a]]
    for (let L = layer[e.a] + 1; L < layer[e.b]; L++) { const it: Item = { key: `slot-${e.i}-${L}`, h: SLOT, y: 0, order: cols[L].length, left: [], right: [] }; cols[L].push(it); chain.push(it) }
    chain.push(item[e.b])
    for (let k = 0; k + 1 < chain.length; k++) { chain[k].right.push(chain[k + 1]); chain[k + 1].left.push(chain[k]) }
    return { ...e, chain }
  })

  // 4. order within a column: towards the average position of what each item connects to, swept both ways
  const sweep = (col: Item[], side: 'left' | 'right') => {
    const want = new Map(col.map(it => [it, it[side].length ? it[side].reduce((s, o) => s + o.order, 0) / it[side].length : it.order]))
    col.sort((p, q) => want.get(p)! - want.get(q)! || p.order - q.order).forEach((it, k) => { it.order = k })
  }
  for (let round = 0; round < 4; round++) {
    for (let L = 1; L < nL; L++) sweep(cols[L], 'left')
    for (let L = nL - 2; L >= 0; L--) sweep(cols[L], 'right')
  }

  // 5. coordinates, every column centred on the tallest
  const colH = cols.map(c => c.reduce((s, it) => s + it.h, 0) + Math.max(0, c.length - 1) * GAPY)
  let H = names.length ? Math.max(NH, ...colH) + 2 * PAD : PAD
  let W = names.length ? 2 * PAD + nL * NW + (nL - 1) * GAPX : 2 * PAD
  const colX = (L: number) => PAD + L * (NW + GAPX)
  cols.forEach((c, L) => { let y = (H - colH[L]) / 2; for (const it of c) { it.y = y; y += it.h + GAPY } })
  const nodes: Record<string, Box> = {}
  for (const n of names) nodes[n] = { x: colX(layer[n]), y: item[n].y, w: NW, h: NH }

  // ports: the feeds on one side of a card are spread down that side, in the order of where they go
  const port = new Map<string, number>()
  for (const n of names) for (const side of ['L', 'R'] as const) {
    const ends = chains.filter(c => (side === 'R' ? c.chain[0] : c.chain[c.chain.length - 1]) === item[n])
      .map(c => ({ c, other: side === 'R' ? c.chain[1] : c.chain[c.chain.length - 2] }))
      .sort((p, q) => (p.other.y + p.other.h / 2) - (q.other.y + q.other.h / 2) || p.c.i - q.c.i)
    ends.forEach((x, k) => port.set(`${x.c.i}${side}`, item[n].y + (k + 1) * NH / (ends.length + 1)))
  }

  const labels: { L: number; e: LaidEdge }[] = []
  const laid = chains.map(c => {
    // the points the feed passes, left to right: out of the first card, across each slot, into the last card
    const pts: [number, number][] = []
    const first = layer[c.a]
    c.chain.forEach((it, k) => {
      const L = first + k, cy = it.y + it.h / 2
      if (k === 0) pts.push([colX(L) + NW, port.get(`${c.i}R`)!])
      else if (k === c.chain.length - 1) pts.push([colX(L), port.get(`${c.i}L`)!])
      else { pts.push([colX(L), cy]); pts.push([colX(L) + NW, cy]) }
    })
    if (c.rev) pts[0][0] += 3; else pts[pts.length - 1][0] -= 3            // room for the arrowhead at the true target
    const seq = c.rev ? [...pts].reverse() : pts
    let d = `M${seq[0][0]},${seq[0][1]}`
    for (let k = 1; k < seq.length; k++) {
      const [x1, y1] = seq[k - 1], [x2, y2] = seq[k]
      // every second stretch is straight across a slot
      d += k % 2 === 0 ? ` L${x2},${y2}` : ` C${x1 + (x2 - x1) / 2},${y1} ${x2 - (x2 - x1) / 2},${y2} ${x2},${y2}`
    }
    // the label sits in the gap beside the left-hand card, on the feed, where no card can be
    const [x1, y1] = pts[0], [x2, y2] = pts[1], w = labelW(c.i)
    const e: LaidEdge = { i: c.i, d, reversed: c.rev, label: { x: (x1 + x2) / 2 - w / 2, y: (y1 + y2) / 2 - LABEL_H / 2, w, h: LABEL_H } }
    labels.push({ L: first, e })
    return e
  })
  // labels in one gap are kept off each other
  for (let L = 0; L < nL; L++) {
    const here = labels.filter(l => l.L === L).map(l => l.e.label).sort((p, q) => p.y - q.y)
    for (let k = 1; k < here.length; k++) if (here[k].y < here[k - 1].y + LABEL_H + LABEL_GAP) here[k].y = here[k - 1].y + LABEL_H + LABEL_GAP
    if (here.length) H = Math.max(H, here[here.length - 1].y + LABEL_H + PAD)
  }
  if (alone.length) {
    const per = Math.max(1, Math.min(alone.length, Math.max(4, Math.floor((W - 2 * PAD + GAPY) / (NW + GAPY)))))
    const rowW = (n: number) => n * NW + (n - 1) * GAPY
    W = Math.max(W, rowW(per) + 2 * PAD)
    alone.forEach((n, k) => {
      const row = Math.floor(k / per), inRow = Math.min(per, alone.length - row * per)
      nodes[n] = { x: (W - rowW(inRow)) / 2 + (k % per) * (NW + GAPY), y: H + row * (NH + GAPY), w: NW, h: NH }
    })
    H += Math.ceil(alone.length / per) * (NH + GAPY) - GAPY + PAD
    if (names.length && W > 2 * PAD + nL * NW + (nL - 1) * GAPX) {            // the rows are wider than the feeds: centre the feeds over them
      const dx = (W - (2 * PAD + nL * NW + (nL - 1) * GAPX)) / 2
      for (const n of names) nodes[n].x += dx
      for (const e of laid) { e.label.x += dx; e.d = e.d.replace(/(-?[\d.]+),(-?[\d.]+)/g, (_m, x, y) => `${Number(x) + dx},${y}`) }
    }
  }
  return { W, H, nodes, edges: laid.sort((p, q) => p.i - q.i) }
}

export const overlaps = (p: Box, q: Box, pad = 0) => p.x < q.x + q.w + pad && q.x < p.x + p.w + pad && p.y < q.y + q.h + pad && q.y < p.y + p.h + pad
