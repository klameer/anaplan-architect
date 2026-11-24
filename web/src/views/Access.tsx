// Who can see a workspace: Private (its maker only) or Shared with the maker's team. Said on the workspace page, in
// the switcher, on the new-workspace page and above the chat box, so nobody types into a shared workspace thinking it
// is theirs alone. Changing it is the maker's; the dialog names who gains or loses access before it happens.
import React, { useEffect, useState } from 'react'
import { api, json } from '../api'
import { useApp } from '../App'

export type Access = { visibility: 'private' | 'shared'; team: string | null; creator: string | null; mine: boolean; can_change: boolean; can_share: boolean; share_locked?: string | null; my_team: string | null; members: string[]; chats: string }
const LOCK = 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z', PEOPLE = 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20a6 6 0 0 1 12 0M17 11a2.5 2.5 0 1 0 0-5M17 14a5 5 0 0 1 4 5'
const Ico = ({ d }: { d: string }) => <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>

/** A small tag: private, or shared with which team. */
export const AccessTag = ({ visibility, team }: { visibility?: string; team?: string | null }) => visibility === 'shared'
  ? <span className="ds-tag sky" data-access="shared" title={`Shared with ${team}: everyone in that team can open it`}><Ico d={PEOPLE} /> shared · {team}</span>
  : <span className="ds-tag" data-access="private" title="Private: only the login that made it can open it"><Ico d={LOCK} /> private</span>

/** The two choices, with one line under each. Shared is offered only to a login that is in a team. */
export function AccessChoice({ value, onChange, team }: { value: 'private' | 'shared'; onChange: (v: 'private' | 'shared') => void; team: string | null }) {
  return <div className="ds-access-choice" role="radiogroup" aria-label="Who can see this workspace">
    <button type="button" role="radio" aria-checked={value === 'private'} className={value === 'private' ? 'on' : ''} onClick={() => onChange('private')}>
      <span className="t"><Ico d={LOCK} /> Private</span><span className="d">Only you can open it. Nobody else sees its models, documents, chats or notes.</span></button>
    <button type="button" role="radio" aria-checked={value === 'shared'} className={value === 'shared' ? 'on' : ''} disabled={!team} onClick={() => team && onChange('shared')}>
      <span className="t"><Ico d={PEOPLE} /> Shared{team ? ` with ${team}` : ''}</span>
      <span className="d">{team ? `Everyone in ${team} can open it, ask in it and add to it. Nobody outside ${team} can.` : 'You are not in a team, so there is nobody to share with. The admin sets your team.'}</span></button>
  </div>
}

/** One line for the chat box: who will be able to read what is typed here. */
export const AccessNote = ({ a }: { a?: Access | null }) => a ? <div className={'ds-access-note' + (a.visibility === 'shared' ? ' shared' : '')} data-access-note={a.visibility}>
  <Ico d={a.visibility === 'shared' ? PEOPLE : LOCK} /><span>{a.chats}</span></div> : null

/** On the workspace page: who can see it, and the maker's way to change that. */
export function AccessStrip({ eid, a }: { eid: string; a: Access }) {
  const { refresh, reloadEstates, toast, me } = useApp()
  const [ask, setAsk] = useState<'private' | 'shared' | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!ask) return; const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setAsk(null) }; document.addEventListener('keydown', esc); return () => document.removeEventListener('keydown', esc) }, [ask])
  if (!me?.user) return null                                  // a server with no logins has one person and nothing to share
  const shared = a.visibility === 'shared'
  const others = a.members.filter(n => n !== a.creator)
  async function change() {
    if (!ask || busy) return
    setBusy(true)
    try { await api('/api/estates/' + eid, json('PATCH', { visibility: ask })); toast(ask === 'shared' ? `Shared with ${a.my_team}.` : 'Private again.'); setAsk(null); await reloadEstates(); await refresh() }
    catch (e: any) { toast(e.message) }
    finally { setBusy(false) }
  }
  return <div className={'ds-access' + (shared ? ' shared' : '')} data-access-strip={a.visibility}>
    <AccessTag visibility={a.visibility} team={a.team} />
    <span className="aw">{shared ? <>Everyone in <b>{a.team}</b> can open it: {a.members.join(', ')}. {a.creator ? <>Made by {a.mine ? 'you' : a.creator}.</> : <>Its maker has left {a.team}: the admin names a new one.</>}</> : a.mine ? 'Only you can open it.' : `Only ${a.creator} can open it.`}</span>
    <span className="grow" />
    {a.mine && (shared ? <button className="ds-btn" onClick={() => setAsk('private')}>Make private…</button>
      : a.can_share ? <button className="ds-btn" onClick={() => setAsk('shared')}>Share with {a.my_team}…</button>
        : a.share_locked ? <span className="dim" style={{ fontSize: 12 }} data-share-locked="1">It cannot be shared with a team: {a.share_locked}. The admin can allow it.</span>
        : <span className="dim" style={{ fontSize: 12 }}>You are not in a team, so it cannot be shared.</span>)}
    {!a.mine && shared && <span className="dim" style={{ fontSize: 12 }}>{a.creator ? <>Only {a.creator} or the admin can change this or delete it. You can add to it, and change or remove what you added.</> : <>You can add to it, and change or remove what you added.</>}</span>}
    {ask && <div className="ds-modal" role="dialog" aria-modal="true" aria-label={ask === 'shared' ? 'Share this workspace' : 'Make this workspace private'} onMouseDown={e => { if (e.target === e.currentTarget) setAsk(null) }}>
      <div className="box">
        {ask === 'shared' ? <>
          <div className="h">Share this workspace with {a.my_team}?</div>
          <div className="what"><div className="k">What changes</div><ul>
            <li>Everyone in {a.my_team} can open it, now and for as long as they are in the team.</li>
            <li>They see its models, documents, notes and every chat in it, including the ones you have already had.</li>
            <li>They can ask, add documents and notes, and upload new exports. Each chat, note and document shows who asked or added it.</li>
            <li>Only you or the admin can make it private again or delete it. Nobody outside {a.my_team} can see it.</li></ul></div></>
          : <>
            <div className="h">Make this workspace private?</div>
            <div className="what"><div className="k">Who loses access</div>
              {others.length ? <ul>{others.map(n => <li key={n}>{n}</li>)}</ul> : <p style={{ margin: '6px 0' }}>Nobody else is in {a.team} yet.</p>}
              <div className="warn">They lose it at once. What they asked and added stays in the workspace, for you.</div></div></>}
        <div className="acts"><button className="ds-btn" onClick={() => setAsk(null)}>Cancel</button><button className="ds-btn go" disabled={busy} onClick={change}>{busy ? 'Saving…' : ask === 'shared' ? `Share with ${a.my_team}` : 'Make private'}</button></div>
      </div></div>}
  </div>
}
