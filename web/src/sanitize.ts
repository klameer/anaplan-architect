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
  return DOMPurify.sanitize(html, SANITIZE) as unknown as string
}

// for tools/ui_check.py, which asks a real browser what survives
;(window as any).__architectSanitize = sanitize
