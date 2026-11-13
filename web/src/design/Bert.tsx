// Bert, the CodelessOps mascot, as a companion around the work: a still image and, where there is one, a short line.
//
// The boundary (Karim, 2026-11-13: "a fun idea but a serious tool"): Bert sits around the answers, never in them.
// Nothing of him inside an answer's figures, citations, diagrams, the context view, the run timeline or the verdict.
// He is used as he is: the signed stills of the Architect variant, copied into ./brand from the brand kit, never
// redrawn and never read from that folder at run time. A still does not move, so nothing here needs a reduced-motion
// rule: there is no animation to turn off. One per page section, beside the content, never the page's hero.
// The only lines set beside him are the ones his spec gives ("Still investigating."); everywhere else the words
// next to him are the page's own plain words, not his.
import React from 'react'
import hello from './brand/bert-architect-hello.svg'
import information from './brand/bert-architect-information.svg'
import processing from './brand/bert-architect-processing.svg'
import investigating from './brand/bert-architect-investigating.svg'
import error from './brand/bert-architect-error.svg'
import warning from './brand/bert-architect-warning.svg'
import neutral from './brand/bert-architect-neutral.svg'
import question from './brand/bert-architect-question.svg'

const STILL = { hello, information, processing, investigating, error, warning, neutral, question }
export type BertState = keyof typeof STILL

/** `place` names where he stands, for the browser check that he is where he should be and nowhere else. */
export function Bert({ state, size = 64, place, line }: { state: BertState; size?: number; place: string; line?: string }) {
  return (
    <span className="ds-bert-fig" data-bert={state} data-bert-place={place}>
      <img src={STILL[state]} alt="" aria-hidden="true" width={Math.round(size * 7 / 6)} height={size} draggable={false} />
      {line && <span className="ln">{line}</span>}
    </span>
  )
}

/** An empty, waiting or failed state: Bert beside the page's own words. */
export function BertNote({ state, place, title, children, line, size = 72 }: { state: BertState; place: string; title: string; children?: React.ReactNode; line?: string; size?: number }) {
  return (
    <div className="ds-bert-note">
      <Bert state={state} place={place} size={size} />
      <div><div className="h">{title}</div>{children && <div className="b">{children}</div>}{line && <div className="ln">{line}</div>}</div>
    </div>
  )
}
