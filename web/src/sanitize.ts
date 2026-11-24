// What an answer, a note or a document passage may contain once it is HTML. Text the model wrote can be steered by
// text it read (a hostile document, an export's notes column), so nothing in it may make the browser ask another site
// for anything: an image address is a way to carry formulas or notes out. Images, media, frames, forms and styles are
// dropped; links stay but open nothing by themselves. The server's Content-Security-Policy says the same to the
// browser, so this is the second lock, not the only one.
import DOMPurify from 'dompurify'

export const SANITIZE = {
  FORBID_TAGS: ['img', 'picture', 'source', 'video', 'audio', 'track', 'iframe', 'frame', 'object', 'embed', 'form', 'input', 'button', 'style', 'link', 'meta', 'base', 'svg', 'math'],
  FORBID_ATTR: ['style', 'srcset', 'background', 'poster', 'ping', 'action', 'formaction'],
}

export function sanitize(html: string): string {
  return outside(DOMPurify.sanitize(html, SANITIZE) as unknown as string)
}

// A link in an answer can be one the model was steered into writing by text it read. It stays a link, but it never
// passes for part of the app: the site it goes to is written beside it, it opens in a tab of its own, and it tells
// that site nothing about where it came from (security review 2026-11-24).
function outside(html: string): string {
  if (!/<a\b/i.test(html)) return html
  const t = document.createElement('template')
  t.innerHTML = html
  t.content.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || ''
    if (href.startsWith('#')) return
    let host = ''
    try { const u = new URL(href, location.href); host = u.origin === location.origin ? '' : (u.host || u.protocol.replace(':', '')) } catch { host = 'an address that could not be read' }
    if (!host) return
    a.setAttribute('rel', 'noopener noreferrer nofollow')
    a.setAttribute('target', '_blank')
    a.setAttribute('data-outside', host)
    const s = document.createElement('span')
    s.className = 'ext-host'
    s.textContent = ` (goes to ${host} ↗)`
    a.after(s)
  })
  return t.innerHTML
}

// for tools/ui_check.py, which asks a real browser what survives
;(window as any).__architectSanitize = sanitize
