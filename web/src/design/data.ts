// The design sheet's data (v0.2 P0, docs/DESIGN.md). Live where the app already has it: the summary (treemap, feeds),
// the reach of SYS05 FX Rates, the action plan, the owner notes. Mocked where the feeding phase is not built:
// project documents (P1/P4) and the build plan (P3). Everything here is the Caldergate demo estate and nothing else:
// the sheet refuses to draw any other estate (AGENTS rule 1).
import { api, type Plan, type Reach, type Summary } from '../api'

export const CALDERGATE = '20260928-160418-965f'
export const FPA = 'Caldergate FP&A'
export const REACH_OF = 'SYS05 FX Rates'

export type NoteLite = { id: string; title: string; type: string; body: string; scope_labels: string[]; updated?: string }
export type Live = { summary: Summary; reach: Reach; plan: Plan; notes: NoteLite[] }

export async function loadLive(): Promise<Live> {
  const E = '/api/estates/' + CALDERGATE
  const summary = await api<Summary>(E)
  if (!/caldergate/i.test(summary.name)) throw new Error('The design sheet draws the Caldergate demo estate only.')
  const [reach, plan, notes] = await Promise.all([
    api<Reach>(`${E}/deps/reach?model=${encodeURIComponent(FPA)}&ref=${encodeURIComponent(REACH_OF)}`),
    api<Plan>(E + '/plan'),
    api<any>(E + '/notes').then(n => (Array.isArray(n) ? n : n.notes || []) as NoteLite[]),
  ])
  return { summary, reach, plan, notes }
}

export type PatternKey = 'why' | 'plan' | 'overview' | 'improve' | 'implications'
export const PATTERNS: { key: PatternKey; label: string; q: string; icon: string; live: string; mock: string }[] = [
  { key: 'why', label: 'Why', q: 'Why is the account mapping written into the Forecast Opex formula instead of a lookup table?',
    icon: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4', live: 'the owner note, the line item figures, the test behind it', mock: 'the project documents and their passages (P1, P4)' },
  { key: 'plan', label: 'Build plan', q: 'Give me a plan to build scenario planning for FY27: flex volumes, price and opex by scenario, P&L by cost centre.',
    icon: 'M4 5h6v5H4zM14 14h6v5h-6zM10 7.5h3.5v9H14', live: 'every existing module and line item the formulas refer to', mock: 'the plan itself: new modules, line items, formulas, order (P3)' },
  { key: 'overview', label: 'Overview', q: 'Give me an overview of the build.',
    icon: 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z', live: 'treemap, feeds between models, counts, tests, owner notes', mock: 'the prose (the architect writes it in the real thing)' },
  { key: 'improve', label: 'Improve', q: 'How can we improve it?',
    icon: 'M4 18l5-6 4 3 7-9M15 6h5v5', live: 'every card, rank, test and figure (the action plan)', mock: 'nothing' },
  { key: 'implications', label: 'Implications', q: 'What are the implications of changing SYS05 FX Rates?',
    icon: 'M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19z', live: 'reach, rings, modules, actions, other models, coverage gaps, the owner note', mock: 'the two project documents that mention it (P1, P4)' },
]

// ---------- mocked: project documents (written for real in P4 against PLANTED.md) ----------
export type DocPassage = { doc: string; kind: string; where: string; date: string; by: string; before: string; quote: string; after: string; names: string[] }
export const WHY_DOCS: DocPassage[] = [
  { doc: 'FP&A design decision record v1.2.docx', kind: 'Design decision record', where: '4.3 Opex forecast logic · page 9', date: '14 Mar 2019', by: 'implementation partner',
    before: 'Opex is forecast by account from the drivers entered in INP02 Opex Drivers.',
    quote: 'The account-to-driver mapping is held in the Forecast Opex formula rather than in a mapping module. Finance Systems asked that planners should not be able to edit the mapping: a change to it is a model change and goes through the change process.',
    after: 'The cost is formula length. Each new account adds a branch.',
    names: ['CAL03 Opex.Forecast Opex', 'INP02 Opex Drivers'] },
  { doc: 'CR-031 Legal fees driver.pdf', kind: 'Change request', where: 'Requested change · page 1', date: '02 May 2024', by: 'Finance Systems',
    before: 'Legal fees are forecast inside Other Opex today.',
    quote: 'Add a thirteenth branch to Forecast Opex for account 6450 Legal Fees, reading the Legal Fees driver. Moving the mapping to a lookup module was agreed in principle and is not part of this request.',
    after: 'Status: open.',
    names: ['CAL03 Opex.Forecast Opex', 'INP02 Opex Drivers.Legal Fees'] },
]
export const FX_DOCS: DocPassage[] = [
  { doc: 'Partner handover note 2021.docx', kind: 'Handover note', where: '3 Manual steps · page 4', date: '30 Jun 2021', by: 'implementation partner',
    before: '', quote: 'The Treasury FX file is loaded by hand, outside any process, because it is sometimes late and the actuals load must not wait for it.', after: '',
    names: ['SYS05 FX Rates'] },
  { doc: 'Steering meeting notes 2023-11.md', kind: 'Meeting notes', where: 'Item 5 · FX', date: '14 Nov 2023', by: 'Finance Systems',
    before: '', quote: 'Treasury will stop sending the monthly file from December. Revenue USD keeps a fixed 1.27 until a rate feed is agreed.', after: '',
    names: ['SYS05 FX Rates', 'CAL02 Revenue.Revenue USD'] },
]

// ---------- mocked: the build plan (P3 builds it; every reference to an existing object is a real Caldergate name) ----------
export type PlanItem = { name: string; format: string; summary: string; formula: string }
export type PlanModule = { step: number; name: string; state: 'new' | 'fill' | 'exists'; applies: string[]; note: string; items: PlanItem[] }
export const BUILD: PlanModule[] = [
  { step: 1, name: 'INP07 Scenario Drivers', state: 'new', applies: ['Scenarios'], note: 'Three inputs per scenario. No Time: a flex is one number per scenario.', items: [
    { name: 'Volume Flex %', format: 'Number %', summary: 'None', formula: '' },
    { name: 'Price Flex %', format: 'Number %', summary: 'None', formula: '' },
    { name: 'Opex Flex %', format: 'Number %', summary: 'None', formula: '' },
  ] },
  { step: 2, name: 'CAL09 Scenario Planning', state: 'fill', applies: ['Products', 'Regions', 'Scenarios', 'Time'], note: 'Exists and is empty. Revenue and cost of sales under each scenario.', items: [
    { name: 'Scenario Units', format: 'Number', summary: 'Sum', formula: "'CAL01 Volumes'.Sellable Units * (1 + 'INP07 Scenario Drivers'.Volume Flex %)" },
    { name: 'Scenario Price', format: 'Number', summary: 'None', formula: "'INP01 Volumes'.Price * (1 + 'INP07 Scenario Drivers'.Price Flex %)" },
    { name: 'Scenario Revenue', format: 'Number', summary: 'Sum', formula: "Scenario Units * Scenario Price * (1 - 'INP01 Volumes'.Discount %)" },
    { name: 'Scenario Revenue GBP', format: 'Number', summary: 'Sum', formula: "Scenario Revenue * 'SYS05 FX Rates'.Rate to GBP[LOOKUP: 'SYS06 Region Attributes'.Currency]" },
    { name: 'Scenario COGS', format: 'Number', summary: 'Sum', formula: "Scenario Units * 'INP06 Unit Costs'.Landed Cost" },
  ] },
  { step: 3, name: 'CAL13 Scenario Opex', state: 'new', applies: ['Cost Centres', 'Scenarios', 'Time'], note: 'Flexes the opex the P&L already carries, so the IF chain is not copied.', items: [
    { name: 'Scenario Opex', format: 'Number', summary: 'Sum', formula: "'CAL07 P&L by Cost Centre'.Opex * (1 + 'INP07 Scenario Drivers'.Opex Flex %)" },
  ] },
  { step: 4, name: 'CAL14 Scenario P&L', state: 'new', applies: ['Cost Centres', 'Scenarios', 'Time'], note: 'The P&L by cost centre under each scenario, and the gap to Base.', items: [
    { name: 'Revenue', format: 'Number', summary: 'Sum', formula: "'CAL09 Scenario Planning'.Scenario Revenue GBP[SUM: 'SYS04 Product Attributes'.Revenue Cost Centre]" },
    { name: 'COGS', format: 'Number', summary: 'Sum', formula: "'CAL09 Scenario Planning'.Scenario COGS[SUM: 'SYS04 Product Attributes'.Revenue Cost Centre]" },
    { name: 'Gross Margin', format: 'Number', summary: 'Sum', formula: 'Revenue - COGS' },
    { name: 'Opex', format: 'Number', summary: 'Sum', formula: "'CAL13 Scenario Opex'.Scenario Opex" },
    { name: 'Staff Cost', format: 'Number', summary: 'Sum', formula: "'CAL07 P&L by Cost Centre'.Staff Cost" },
    { name: 'EBITDA', format: 'Number', summary: 'Sum', formula: 'Gross Margin - Opex - Staff Cost' },
    { name: 'EBITDA vs Base', format: 'Number', summary: 'Sum', formula: 'EBITDA - EBITDA[SELECT: Scenarios.Base]' },
  ] },
  { step: 5, name: 'OUT03 Scenario Comparison', state: 'new', applies: ['Cost Centres', 'Scenarios', 'Time'], note: 'What the page reads. Nothing calculates here that is not shown.', items: [
    { name: 'EBITDA', format: 'Number', summary: 'Sum', formula: "'CAL14 Scenario P&L'.EBITDA" },
    { name: 'EBITDA vs Base', format: 'Number', summary: 'Sum', formula: "'CAL14 Scenario P&L'.EBITDA vs Base" },
    { name: 'EBITDA Margin', format: 'Number %', summary: 'Formula', formula: "DIVIDE('CAL14 Scenario P&L'.EBITDA, 'CAL14 Scenario P&L'.Revenue)" },
  ] },
]
/** What the plan reads that is already in the model (the diagram's left column), and who reads it. */
export const BUILD_EXISTING = ['CAL01 Volumes', 'INP01 Volumes', 'INP06 Unit Costs', 'SYS05 FX Rates', 'SYS04 Product Attributes', 'CAL07 P&L by Cost Centre']
export const BUILD_EDGES: [string, string][] = [
  ['CAL01 Volumes', 'CAL09 Scenario Planning'], ['INP01 Volumes', 'CAL09 Scenario Planning'], ['INP06 Unit Costs', 'CAL09 Scenario Planning'], ['SYS05 FX Rates', 'CAL09 Scenario Planning'],
  ['SYS04 Product Attributes', 'CAL14 Scenario P&L'], ['CAL07 P&L by Cost Centre', 'CAL13 Scenario Opex'], ['CAL07 P&L by Cost Centre', 'CAL14 Scenario P&L'],
  ['INP07 Scenario Drivers', 'CAL09 Scenario Planning'], ['INP07 Scenario Drivers', 'CAL13 Scenario Opex'],
  ['CAL09 Scenario Planning', 'CAL14 Scenario P&L'], ['CAL13 Scenario Opex', 'CAL14 Scenario P&L'], ['CAL14 Scenario P&L', 'OUT03 Scenario Comparison'],
]

/** The shell's workspace switcher. Mocked: one login, several workspaces arrives in P5. */
export const WORKSPACES = [
  { name: 'Caldergate Distribution Group', sub: '4 models · 5 documents', on: true },
  { name: 'Caldergate FY27 rebuild', sub: '1 model · sandbox', on: false },
]
