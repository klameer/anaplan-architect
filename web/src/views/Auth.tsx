import React, { useState } from 'react'
import { Bert } from '../design/Bert'
import { api, json, type Me } from '../api'
import logoUrl from '../design/brand/logo.svg'

/** Sign in. Nobody creates an account here and there are no invite codes: the admin creates each login and hands
 *  over the username and password. Full-screen: nothing else is reachable without it. The notice says what this
 *  instance is before anyone uploads to it. */
export function Auth({ me, onDone }: { me: Me; onDone: () => void }) {
  const [f, setF] = useState({ email: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })

  async function go() {
    setBusy(true); setErr(null)
    try { await api('/api/auth/login', json('POST', f)); onDone() } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="ds ds-auth">
      <div className="box">
        <div className="ds-brand" style={{ padding: 0, marginBottom: 22 }}><img src={logoUrl} alt="" width="30" height="30" /><span><span className="wm" style={{ fontSize: 17 }}><b>/</b>architect</span><span className="by">by CodelessOps</span></span><span className="grow" /><Bert state="hello" place="sign-in" size={60} /></div>
        <div className="ds-tagline">your Anaplan build buddy</div>
        {me.closed ? <>
          <h1>No logins on this server yet</h1>
          <p className="dim">It is bound to the network, so it serves nothing until its admin exists. Whoever runs the server creates the admin from its console:</p>
          <pre>{me.console_hint}</pre>
          <p className="dim">After that, the admin signs in here and creates every other login from the admin panel.</p>
        </> : <>
          <h1>Sign in</h1>
          <p className="dim">For Anaplan model builders: upload your line item, module and action exports and your project documents, then ask. Every answer is cited and checked.</p>
          <label className="k" htmlFor="u">Username</label><input id="u" value={f.email} onChange={set('email')} autoComplete="username" autoFocus />
          <label className="k" htmlFor="p">Password</label><input id="p" value={f.password} onChange={set('password')} type="password" autoComplete="current-password" onKeyDown={e => { if (e.key === 'Enter') go() }} />
          <button className="go" disabled={busy || !f.email || !f.password} onClick={go}>{busy ? 'Signing in…' : 'Sign in'}</button>
          {err && <p className="ds-gap" style={{ marginTop: 12 }}>{err}</p>}
          <p className="dim small">There is no signup. Logins are created by the person who runs this instance.</p>
          <p className="dim small">Not affiliated with or endorsed by Anaplan.</p>
          {me.notice && <div className="ds-none" style={{ marginTop: 16 }}><div className="h">Before you upload</div><div style={{ fontSize: 13 }}>{me.notice}</div></div>}
        </>}
      </div>
    </div>
  )
}
