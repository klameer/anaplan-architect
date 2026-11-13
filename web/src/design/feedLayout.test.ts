// npm test (in web/): the model map never puts a card on a card or a label on a card, at 1, 2, 4 and 8 models, with
// feeds both ways, loops, feeds that skip a column, and models nothing feeds.
declare const process: { exit(code: number): never }
import { layoutFeeds, overlaps, NW, NH, type FEdge } from './feedLayout'

let failed = 0
const check = (label: string, ok: boolean, detail = '') => { if (!ok) failed++; console.log((ok ? '  ok   ' : '  FAIL ') + label + (ok || !detail ? '' : `  [${detail}]`)) }

function sound(label: string, names: string[], edges: FEdge[]) {
  const l = layoutFeeds(names, edges, i => i % 3 === 0 ? 54 : 26)
  const boxes = names.map(n => l.nodes[n])
  const bad: string[] = []
  for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) if (overlaps(boxes[a], boxes[b], 8)) bad.push(`${names[a]} on ${names[b]}`)
  for (const e of l.edges) for (let a = 0; a < boxes.length; a++) if (overlaps(e.label, boxes[a], 2)) bad.push(`label ${e.i} on ${names[a]}`)
  for (let a = 0; a < l.edges.length; a++) for (let b = a + 1; b < l.edges.length; b++) if (overlaps(l.edges[a].label, l.edges[b].label)) bad.push(`label ${a} on label ${b}`)
  for (const b of [...boxes, ...l.edges.map(e => e.label)]) if (b.x < 0 || b.y < 0 || b.x + b.w > l.W || b.y + b.h > l.H) bad.push('outside the drawing')
  if (boxes.some(b => b.w !== NW || b.h !== NH)) bad.push('card size')
  const real = edges.filter(e => e.from !== e.to && names.includes(e.from) && names.includes(e.to)).length
  if (l.edges.length !== real) bad.push(`${l.edges.length} of ${real} feeds drawn`)
  if (l.edges.some(e => /NaN|undefined/.test(e.d))) bad.push('a path with no number in it')
  check(`${label}: ${names.length} models, ${real} feeds, ${l.W} x ${Math.round(l.H)}`, !bad.length, bad.slice(0, 4).join('; '))
  return l
}

const E = (s: string): FEdge[] => s.split(' ').filter(Boolean).map(p => { const [from, to] = p.split('>'); return { from, to } })
sound('one model', ['A'], [])
sound('two models, one feed', ['A', 'B'], E('A>B'))
const two = sound('two models, feeds both ways', ['A', 'B'], E('A>B B>A'))
check('  both ways: one of the two is drawn against the layout, neither is dropped', two.edges.filter(e => e.reversed).length === 1)
sound('four models in a chain', ['Hub', 'FPA', 'WFP', 'Board'], E('Hub>FPA Hub>WFP FPA>Board WFP>FPA'))
const four = sound('four models, all feeding each other', ['FPA', 'Pipeline', 'HR', 'Hub'], E('Hub>FPA Hub>Pipeline Hub>HR FPA>Pipeline Pipeline>FPA HR>FPA FPA>HR Pipeline>HR FPA>Hub'))
check('  the four are spread over the drawing, not bunched at one side', Math.min(...Object.values(four.nodes).map(b => b.x)) < 20 && new Set(Object.values(four.nodes).map(b => b.x)).size >= 2)
sound('four models, no feeds', ['A', 'B', 'C', 'D'], [])
sound('five models, two of them with no feed', ['A', 'B', 'C', 'Lone 1', 'Lone 2'], E('A>B B>C'))
sound('seven models with no feed and one pair', ['A', 'B', 'L1', 'L2', 'L3', 'L4', 'L5'], E('A>B B>A'))
sound('eight models, a hub and spokes both ways', ['Hub', 'A', 'B', 'C', 'D', 'E', 'F', 'G'], E('Hub>A Hub>B Hub>C Hub>D Hub>E Hub>F Hub>G A>Hub C>Hub G>Hub'))
sound('eight models, a long chain with feeds that skip columns', ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8'], E('M1>M2 M2>M3 M3>M4 M4>M5 M5>M6 M6>M7 M7>M8 M1>M5 M2>M8 M8>M1 M3>M7 M6>M2'))
sound('eight models, dense', ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'], E('A>B A>C A>D B>E C>E D>E E>F E>G F>H G>H H>A B>C C>B D>H A>H F>B'))
sound('a ring of three', ['A', 'B', 'C'], E('A>B B>C C>A'))
sound('a feed to a model that is not there is ignored', ['A', 'B'], E('A>B A>Z Z>B A>A'))
const skip = layoutFeeds(['A', 'B', 'C'], E('A>B B>C A>C'))
check('a feed that skips a column runs clear of the card in that column', (() => { const b = skip.nodes['B']; const m = /L([\d.]+),([\d.]+)/.exec(skip.edges[2].d); return !!m && (Number(m[2]) < b.y - 4 || Number(m[2]) > b.y + b.h + 4) })(), skip.edges[2].d)

// Caldergate: FP&A to Workforce Planning no longer runs; the live feeds decide the order, the retired one follows them
const cg = ['Hub', 'FPA', 'WFP', 'Board'], cge = E('Hub>FPA FPA>Board WFP>FPA Hub>WFP FPA>WFP WFP>Board')
const live = layoutFeeds(cg, cge, () => 26, i => i === 4)
check('a feed that no longer runs does not shape the map: the live order is Hub, WFP, FPA, Board', ['Hub', 'WFP', 'FPA', 'Board'].every((n, k, a) => k === 0 || live.nodes[a[k - 1]].x < live.nodes[n].x)
  && live.edges[4].reversed && live.edges.filter(e => e.reversed).length === 1, JSON.stringify(live.nodes))
sound('the same with the retired feed weak, by the sound() rules', cg, cge)
const pair = layoutFeeds(['A', 'B'], E('A>B B>A'), () => 26, i => i === 0)
check('two models, the live feed left to right and the retired one against it', pair.nodes['B'].x < pair.nodes['A'].x && pair.edges[0].reversed && !pair.edges[1].reversed)

console.log(failed ? `\n${failed} failed` : '\nall passed')
process.exit(failed ? 1 : 0)
