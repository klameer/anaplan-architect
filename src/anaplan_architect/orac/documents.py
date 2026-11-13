"""Project documents in a workspace (v0.2 P1): read once at upload, split into sections by heading, searched by
keyword and by the objects each section names. No vectors, no embeddings: FTS5 and structured links only.

What reaches the model: every document's card, always (title, type, date, headings, a summary written once at
upload, the objects it names); and, per question, only the sections a tool pulled. Never a whole document.

Limits, stated on the page and in the README: MAX_DOCS project documents per workspace, MAX_BYTES each. A PDF with
no text layer (a scan) is kept with a problem line saying so: there is no OCR.
"""
from __future__ import annotations
import hashlib, io, json, re, secrets, zipfile, unicodedata
from .db import Db, now

MAX_DOCS = 20
MAX_BYTES = 10 * 1024 * 1024
MAX_UNZIPPED = 40 * 1024 * 1024    # what a Word file's document.xml may unzip to: a 10 MB file that claims more is not a document
MAX_SECTION_CHARS = 6000          # a section longer than this is split at paragraph ends, so one pull stays small
TEXT_EXT = {"md", "markdown", "txt", "text", "csv", "tsv", "py", "sql", "sh", "ps1", "js", "json", "yaml", "yml", "ini", "cfg", "log", "rst"}
SCRIPT_EXT = {"py", "sql", "sh", "ps1", "js"}
SECTION_ID = re.compile(r"\bs-[0-9a-f]{10}\b")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&%?/.-]*")


def tokens_of(text: str) -> int:
    """An estimate, the same everywhere a size is shown: four characters to a token."""
    return (len(text or "") + 3) // 4


def section_id(doc_id: str, seq: int) -> str:
    return "s-" + hashlib.sha1(f"{doc_id}\x1f{seq}".encode()).hexdigest()[:10]


# ---------- reading a file ----------
def _docx_blocks(body: bytes) -> list[tuple[int, str]]:
    """(heading level or 0, text) per paragraph of a Word file, read from word/document.xml: no dependency."""
    from xml.etree import ElementTree as ET
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if z.getinfo("word/document.xml").file_size > MAX_UNZIPPED:           # looked at before anything is unzipped
            raise OverflowError("the Word file is too large once opened")
        with z.open("word/document.xml") as f:
            xml = f.read(MAX_UNZIPPED + 1)                                    # and the read itself stops there, whatever the header claimed
        if len(xml) > MAX_UNZIPPED:
            raise OverflowError("the Word file is too large once opened")
        root = ET.fromstring(xml)
    out = []
    for p in root.iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if not text:
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        sv = (style.get(W + "val") if style is not None else "") or ""
        m = re.match(r"(?i)heading\s*([1-6])", sv)
        out.append((int(m.group(1)) if m else (1 if sv.lower() == "title" else 0), text))
    return out


def _pdf_text(body: bytes) -> tuple[str, str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "PDF reading needs the pypdf package on the server"
    try:
        reader = PdfReader(io.BytesIO(body))
        pages = [(pg.extract_text() or "").strip() for pg in reader.pages]
    except Exception as e:
        return "", f"could not read the PDF: {type(e).__name__}"
    text = "\n\n".join(f"## Page {i + 1}\n\n{t}" for i, t in enumerate(pages) if t)
    if not text.strip():
        return "", "no text found: this looks like a scanned PDF, and scanned pages are not read (no OCR)"
    return text, None


_MD_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_NUM_HEAD = re.compile(r"^(\d+(?:\.\d+){0,3})[.)]?\s+([A-Z][^.!?]{2,80})$")
_DEF = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)")


def _blocks(text: str, ext: str) -> list[tuple[int, str]]:
    """(heading level or 0, text) per line group: markdown headings, numbered headings ("4.3 Opex forecast logic"),
    an underlined heading, and for a script every def or class."""
    out: list[tuple[int, str]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    if ext not in SCRIPT_EXT and lines and lines[0].strip() == "---":          # YAML front matter: not text, and never headings
        end = next((k for k in range(1, min(len(lines), 80)) if lines[k].strip() in ("---", "...")), None)
        if end is not None and all(re.match(r"\s*(#.*)?$|\s*[\w.-]+\s*:|\s+\S|\s*-\s", ln) for ln in lines[1:end]):
            t = next((m.group(1).strip().strip("\"'") for m in (re.match(r"(?i)\s*title\s*:\s*(.+)$", ln) for ln in lines[1:end]) if m), "")
            if t:
                out.append((1, t))                                             # the title it gives names the document
            i = end + 1
    while i < len(lines):
        ln = lines[i]
        m = _MD_HEAD.match(ln)
        if m and ext not in SCRIPT_EXT:
            out.append((len(m.group(1)), m.group(2).strip())); i += 1; continue
        if i + 1 < len(lines) and ln.strip() and re.fullmatch(r"\s*(=+|-{3,})\s*", lines[i + 1]) and ext not in SCRIPT_EXT:
            out.append((1 if lines[i + 1].strip().startswith("=") else 2, ln.strip())); i += 2; continue
        m = _NUM_HEAD.match(ln.strip())
        if m and ext not in SCRIPT_EXT and ext not in ("csv", "tsv") and (i == 0 or not lines[i - 1].strip()) and (i + 1 >= len(lines) or not lines[i + 1].strip()):
            out.append((min(6, m.group(1).count(".") + 1), ln.strip())); i += 1; continue
        m = _DEF.match(ln) if ext in SCRIPT_EXT else None
        if m and not ln.startswith((" ", "\t")):
            out.append((2, m.group(1) + "()" if ln.lstrip().startswith("def") else m.group(1)))
        out.append((0, ln)); i += 1
    return out


def split_sections(blocks: list[tuple[int, str]], title: str) -> list[dict]:
    """Sections by heading, in order. Text before the first heading is the opening section. A long section is cut at
    paragraph ends into parts that carry the same heading."""
    secs: list[dict] = []
    cur = {"heading": "", "level": 1, "lines": []}
    doc_title = next((t for lvl, t in blocks if lvl == 1), "")          # the first top-level heading, whether or not text sits under it
    for lvl, text in blocks:
        if lvl:
            if "".join(cur["lines"]).strip():
                secs.append(cur)
            cur = {"heading": text, "level": lvl, "lines": []}
        else:
            cur["lines"].append(text)
    if "".join(cur["lines"]).strip() or (cur["heading"] and not secs):
        secs.append(cur)
    out = []
    for s in secs:
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(s["lines"])).strip()
        if not body:
            continue
        head = s["heading"] or (title if not out else "")
        parts, buf = [], ""
        for para in re.split(r"\n\s*\n", body):
            if buf and len(buf) + len(para) > MAX_SECTION_CHARS:
                parts.append(buf); buf = ""
            buf = (buf + "\n\n" + para) if buf else para
            while len(buf) > MAX_SECTION_CHARS * 2:          # one enormous paragraph (a CSV, a log): cut hard
                parts.append(buf[:MAX_SECTION_CHARS]); buf = buf[MAX_SECTION_CHARS:]
        if buf:
            parts.append(buf)
        for n, part in enumerate(parts):
            out.append({"heading": head + (f" (part {n + 1})" if len(parts) > 1 else ""), "level": s["level"], "text": part})
    if out and doc_title:
        out[0]["title"] = doc_title
    return out


def read_file(filename: str, body: bytes) -> tuple[list[dict], str | None, str]:
    """(sections, problem, ext) for an uploaded file."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    title = filename.rsplit(".", 1)[0]
    problem = None
    if ext == "docx":
        try:
            blocks = _docx_blocks(body)
        except OverflowError as e:
            return [], f"{e}: it was not read", ext
        except Exception as e:
            return [], f"could not read the Word file: {type(e).__name__}", ext
    elif ext == "pdf":
        text, problem = _pdf_text(body)
        blocks = _blocks(text, ext)
    elif ext in TEXT_EXT or not ext:
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = body.decode("cp1252", errors="replace")
        blocks = _blocks(text, ext)
    else:
        return [], f"a .{ext} file is not read: upload PDF, Word (.docx), Markdown, text, CSV or a script", ext
    secs = split_sections(blocks, title)
    if not secs and not problem:
        problem = "no text found in the file"
    return secs, problem, ext


_TYPES = [("Design decision record", r"decision record|design decision|\bddr\b|design record"), ("Change request", r"change request|\bcr[- ]?\d+"),
          ("Meeting notes", r"steering|meeting|minutes"), ("Handover note", r"handover|hand-over|hand over"),
          ("Test plan", r"test plan|uat"), ("Process note", r"runbook|procedure|process note|how to")]
_DATE = [re.compile(r"\b(20\d\d|19\d\d)-(\d\d)-(\d\d)\b"), re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d\d|19\d\d)\b", re.I),
         re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d\d|19\d\d)\b", re.I), re.compile(r"\b(20\d\d|19\d\d)\b")]
_MON = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def guess_type(filename: str, ext: str, head: str) -> str:
    if ext in SCRIPT_EXT:
        return "Integration script"
    if ext in ("csv", "tsv"):
        return "Data file"
    probe = (filename + " " + head[:400]).lower()
    return next((t for t, pat in _TYPES if re.search(pat, probe)), "Document")


def guess_date(filename: str, head: str) -> str | None:
    """A date the document carries: in its name first, then in its opening lines. Year-month or year when that is all it says."""
    m = _DATE[3].search(filename)
    if m and not any(p.search(filename) for p in _DATE[:3]):          # a year in the name ("... notes 2023") is the document's own date
        return m.group(1)
    for src in (filename, head[:600]):
        m = _DATE[0].search(src)
        if m:
            return m.group(0)
        m = _DATE[1].search(src)
        if m:
            return f"{m.group(3)}-{_MON[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
        m = _DATE[2].search(src)
        if m:
            return f"{m.group(2)}-{_MON[m.group(1)[:3].lower()]:02d}"
    return None


def extract_summary(sections: list[dict], limit: int = 320) -> str:
    """The summary when no model writes one: the first sentences of the opening text."""
    prose = "\n".join(ln for s in sections[:2] for ln in s["text"].split("\n") if ln.strip() and not ln.lstrip().startswith(("|", "#", "```", "import ", "from ")))
    text = re.sub(r"\s+", " ", prose.replace('"""', "")).strip()
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sent) > limit and out:
            break
        out = (out + " " + sent).strip()
    return out[:limit + 80]


# ---------- the objects a section names ----------
def object_index(estate_run) -> list[tuple[str, str, str, re.Pattern]]:
    """(model, kind, ref, pattern) for every module and every Module.Line Item of the parsed estate, longest names first.
    A bare line item name is not linked: `Opex` is a word. A module is matched as a whole name in its own case; a line item as
    `Module.Line Item` or `'Module'.Line Item`."""
    out = []
    for m in estate_run.models:
        for mod in m.model.modules:
            out.append((m.name, "module", mod, re.compile(r"(?<![\w])" + re.escape(mod) + r"(?![\w])")))      # as the module is written: a module called Opex is not the word opex
        for (mod, li) in m.model.line_items:
            out.append((m.name, "line_item", f"{mod}.{li}", re.compile(r"(?<![\w])'?" + re.escape(mod) + r"'?\s*\.\s*'?" + re.escape(li) + r"(?![\w])", re.I)))
    out.sort(key=lambda r: -len(r[2]))
    return out


def link_objects(text: str, index) -> list[tuple[str, str, str]]:
    low = text
    hits = []
    for model, kind, ref, pat in index:
        if pat.search(low):
            hits.append((model, kind, ref))
    return hits


# ---------- the store ----------
def _doc(db: Db, r: dict) -> dict:
    secs = db.q("SELECT id, seq, heading, level, tokens FROM doc_sections WHERE document_id=? ORDER BY seq", r["id"])
    objs = db.q("SELECT o.model, o.kind, o.ref, COUNT(*) AS n FROM doc_section_objects o JOIN doc_sections s ON s.id=o.section_id "
                "WHERE s.document_id=? GROUP BY o.model, o.kind, o.ref ORDER BY n DESC, o.ref", r["id"])
    cited = {x["object_ref"]: x for x in db.q(
        "SELECT c.object_ref, COUNT(DISTINCT c.owner_id) AS answers FROM citations c WHERE c.kind='document' AND c.owner_kind='turn' "
        "AND c.object_ref IN (SELECT id FROM doc_sections WHERE document_id=?) GROUP BY c.object_ref", r["id"])}
    answers = db.one("SELECT COUNT(DISTINCT c.owner_id) AS n FROM citations c WHERE c.kind='document' AND c.owner_kind='turn' "
                     "AND c.object_ref IN (SELECT id FROM doc_sections WHERE document_id=?)", r["id"])["n"]
    return dict(r, sections=[dict(s, cited=cited.get(s["id"], {}).get("answers", 0)) for s in secs], objects=objs,
                tokens=sum(s["tokens"] for s in secs), sections_cited=len(cited), answers=answers)


def list_documents(db: Db, eid: str) -> list[dict]:
    return [_doc(db, r) for r in db.q("SELECT * FROM documents WHERE estate_id=? ORDER BY uploaded_at, rowid", eid)]


def count(db: Db, eid: str) -> int:
    return db.one("SELECT COUNT(*) AS n FROM documents WHERE estate_id=?", eid)["n"]


def get(db: Db, did: str) -> dict:
    r = db.one("SELECT * FROM documents WHERE id=?", did)
    if not r:
        raise KeyError(did)
    return _doc(db, r)


def get_section(db: Db, sid: str, eid: str | None = None) -> dict | None:
    r = db.one("SELECT s.*, d.title AS doc_title, d.doc_type, d.doc_date, d.filename, d.estate_id, d.id AS doc_id, "
               "(SELECT COUNT(*) FROM doc_sections x WHERE x.document_id=d.id) AS of FROM doc_sections s JOIN documents d ON d.id=s.document_id WHERE s.id=?", sid)
    if not r or (eid and r["estate_id"] != eid):
        return None
    r["objects"] = db.q("SELECT model, kind, ref FROM doc_section_objects WHERE section_id=? ORDER BY ref", sid)
    return r


def add(db: Db, eid: str, filename: str, body: bytes, estate_run=None, by: str | None = None, summarise=None, replaces: str | None = None,
        blob_sha: str | None = None, doc_id: str | None = None, summary_text: str | None = None) -> dict:
    """Read, split, link and store one document. `summarise(title, text) -> str` writes the card's summary once (a model
    call when the server has one); without it the opening sentences stand in. Raises ValueError with the limit that was hit."""
    filename = (filename or "document").replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    if len(body) > MAX_BYTES:
        raise ValueError(f"{filename} is {len(body) / 1e6:.1f} MB: a document may be up to {MAX_BYTES // (1024 * 1024)} MB")
    if replaces and not db.one("SELECT 1 FROM documents WHERE id=? AND estate_id=?", replaces, eid):      # nothing to replace: it would be one more document
        raise ValueError("the document to replace is not in this workspace")
    if not replaces and count(db, eid) >= MAX_DOCS:
        raise ValueError(f"this workspace already holds {MAX_DOCS} documents, the limit: these are project documents, not an archive. Remove one first")
    sections, problem, ext = read_file(filename, body)
    title = re.sub(r"[_]+", " ", filename.rsplit(".", 1)[0]).strip() if ext not in SCRIPT_EXT else filename
    first = (sections[0].get("title") if sections else "") or next((s["heading"] for s in sections if s["heading"] and s["level"] == 1), "")
    if first and ext not in SCRIPT_EXT and len(first) <= 90:
        title = first
    head = " ".join(s["text"] for s in sections[:2])
    summary, summary_by = extract_summary(sections), "extract"
    if summary_text:                                   # written by hand and shipped with the file (the demo documents)
        summary, summary_by = summary_text.strip()[:600], "author"
    elif summarise is not None and sections:
        try:
            s = (summarise(title, "\n\n".join((x["heading"] + "\n" if x["heading"] else "") + x["text"] for x in sections)[:12000]) or "").strip()
            if s:
                summary, summary_by = s[:600], "model"
        except Exception:
            pass                                        # the card still has its opening sentences
    index = object_index(estate_run) if estate_run is not None else []
    did = doc_id or "d-" + secrets.token_hex(5)
    prev = db.one("SELECT * FROM documents WHERE id=? AND estate_id=?", replaces, eid) if replaces else None
    with db.tx():
        if prev:
            db.run("DELETE FROM documents WHERE id=?", prev["id"])        # its sections go; citations on old answers keep their quote in the payload
        db.run("INSERT INTO documents(id, estate_id, title, doc_type, filename, ext, bytes, blob_sha, doc_date, summary, summary_by, words, version, replaces, problem, "
               "uploaded_at, uploaded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", did, eid, title[:160], guess_type(filename, ext, head), filename, ext, len(body),
               blob_sha or hashlib.sha256(body).hexdigest(), guess_date(filename, head), summary, summary_by, sum(len(_WORD.findall(s["text"])) for s in sections),
               (prev["version"] + 1) if prev else 1, prev["id"] if prev else None, problem, now(), by)
        for i, s in enumerate(sections):
            sid = section_id(did, i)
            db.run("INSERT INTO doc_sections(id, document_id, seq, heading, level, text, tokens) VALUES (?,?,?,?,?,?,?)", sid, did, i, s["heading"][:200], s["level"],
                   s["text"], tokens_of(s["heading"] + s["text"]))
            for model, kind, ref in link_objects(s["heading"] + "\n" + s["text"], index):
                db.run("INSERT OR IGNORE INTO doc_section_objects(section_id, model, kind, ref) VALUES (?,?,?,?)", sid, model, kind, ref)
    return get(db, did)


def relink(db: Db, eid: str, estate_run) -> int:
    """After a new snapshot is activated: the object links are read again against the estate as it is now."""
    index = object_index(estate_run)
    n = 0
    with db.tx():
        for s in db.q("SELECT s.id, s.heading, s.text FROM doc_sections s JOIN documents d ON d.id=s.document_id WHERE d.estate_id=?", eid):
            db.run("DELETE FROM doc_section_objects WHERE section_id=?", s["id"])
            for model, kind, ref in link_objects(s["heading"] + "\n" + s["text"], index):
                db.run("INSERT OR IGNORE INTO doc_section_objects(section_id, model, kind, ref) VALUES (?,?,?,?)", s["id"], model, kind, ref); n += 1
    return n


def remove(db: Db, did: str) -> dict | None:
    r = db.one("SELECT * FROM documents WHERE id=?", did)
    if r:
        db.run("DELETE FROM documents WHERE id=?", did)
    return r


# ---------- what the model is given ----------
def cards(db: Db, eid: str) -> list[dict]:
    out = []
    for d in list_documents(db, eid):
        heads = [s["heading"] for s in d["sections"] if s["heading"]]
        out.append({"id": d["id"], "title": d["title"], "type": d["doc_type"], "date": d["doc_date"], "sections": len(d["sections"]), "headings": heads[:12],
                    "more_headings": max(0, len(heads) - 12), "summary": d["summary"], "names": list(dict.fromkeys(o["ref"] for o in d["objects"]))[:10], "problem": d["problem"]})
    return out


def cards_text(db: Db, eid: str) -> str:
    """The cards as the model reads them: one short block per document. This is all of a document that is always in context."""
    cs = cards(db, eid)
    if not cs:
        return ""
    lines = ["# Project documents in this workspace (cards only)",
             "Each document below is held in sections. You see only its card. To read a section call search_documents (keyword and object search, "
             "returns section hits with their ids) and then get_section for the ones that bear on the question. Never assume what a section says from its heading.", ""]
    for c in cs:
        lines.append(f"- {c['title']} [{c['id']}; {c['type']}{'; ' + c['date'] if c['date'] else ''}; {c['sections']} sections]"
                     + (f" PROBLEM: {c['problem']}" if c["problem"] else ""))
        if c["summary"]:
            lines.append(f"  Summary: {c['summary']}")
        if c["headings"]:
            lines.append("  Headings: " + " | ".join(c["headings"]) + (f" | +{c['more_headings']} more" if c["more_headings"] else ""))
        if c["names"]:
            lines.append("  Names: " + ", ".join(c["names"]))
    return "\n".join(lines)


_STOP = set("a an and are as at be been but by can did do does for from had has have how i if in into is it its me my no not of on or our so than that the their them then "
            "there these they this to was we were what when where which who why will with would you your about above after again all also any because before being "
            "between both each few more most other some such only own same too very s t just should now built build way like".split())


def _fts_query(q: str) -> str:
    terms = []
    for w in _WORD.findall(q or ""):
        w = w.strip("'.-/").lower()
        if len(w) >= 2 and w not in _STOP and w not in terms:
            terms.append(w)
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms[:16])


def search(db: Db, eid: str, query: str = "", objects: list[str] | None = None, document: str | None = None, limit: int = 6) -> dict:
    """Section hits for a question: FTS5 over headings and text (best match first), plus every section linked to one of the
    named objects. Each hit is a snippet, never the section: get_section reads one."""
    limit = max(1, min(int(limit or 6), 12))
    total = db.one("SELECT COUNT(*) AS n FROM doc_sections s JOIN documents d ON d.id=s.document_id WHERE d.estate_id=?", eid)["n"]
    hits: dict[str, dict] = {}
    fq = _fts_query(query)
    if fq:
        args: list = [fq, eid]
        sql = ("SELECT s.id, s.heading, s.seq, s.tokens, d.id AS doc_id, d.title, d.doc_type, d.doc_date, bm25(doc_sections_fts, 3.0, 1.0) AS score, "
               "snippet(doc_sections_fts, 1, '', '', ' … ', 28) AS snip FROM doc_sections_fts JOIN doc_sections s ON s.rowid=doc_sections_fts.rowid "
               "JOIN documents d ON d.id=s.document_id WHERE doc_sections_fts MATCH ? AND d.estate_id=?")
        if document:
            sql += " AND d.id=?"; args.append(document)
        for r in db.q(sql + " ORDER BY score LIMIT ?", *args, limit * 2):
            hits[r["id"]] = dict(r, why="keyword match", rank=r["score"])
    for name in objects or []:
        ref = (name or "").strip().strip("'")
        if not ref:
            continue
        rows = db.q("SELECT s.id, s.heading, s.seq, s.tokens, s.text, d.id AS doc_id, d.title, d.doc_type, d.doc_date, o.ref FROM doc_section_objects o "
                    "JOIN doc_sections s ON s.id=o.section_id JOIN documents d ON d.id=s.document_id WHERE d.estate_id=? AND (lower(o.ref)=lower(?) OR lower(o.ref) LIKE lower(?)) "
                    + ("AND d.id=? " if document else "") + "ORDER BY d.uploaded_at, s.seq LIMIT 20", eid, ref, ref + ".%", *([document] if document else []))
        for r in rows:
            h = hits.get(r["id"])
            if h:
                h["why"] = f"keyword match; names {r['ref']}"; h["rank"] = h["rank"] - 5        # both signals: first
            else:
                i = r["text"].lower().find(r["ref"].split(".")[-1].lower())
                snip = re.sub(r"\s+", " ", r["text"][max(0, i - 90): i + 150]).strip() if i >= 0 else re.sub(r"\s+", " ", r["text"][:200])
                hits[r["id"]] = dict({k: r[k] for k in ("id", "heading", "seq", "tokens", "doc_id", "title", "doc_type", "doc_date")}, snip=snip,
                                     why=f"names {r['ref']}", rank=-1.0)
    ordered = sorted(hits.values(), key=lambda h: h["rank"])[:limit]
    return {"hits": [{"section": h["id"], "document": h["title"], "document_id": h["doc_id"], "type": h["doc_type"], "date": h["doc_date"], "heading": h["heading"],
                      "tokens": h["tokens"], "why": h["why"], "snippet": re.sub(r"\s+", " ", h["snip"])[:300]} for h in ordered],
            "matched": len(hits), "sections_in_workspace": total}


def totals(db: Db, eid: str) -> dict:
    r = db.one("SELECT COUNT(DISTINCT d.id) AS documents, COUNT(s.id) AS sections, COALESCE(SUM(s.tokens),0) AS tokens FROM documents d "
               "LEFT JOIN doc_sections s ON s.document_id=d.id WHERE d.estate_id=?", eid)
    return dict(r, max_documents=MAX_DOCS, max_bytes=MAX_BYTES)


# ---------- checking a quoted passage ----------
MAX_QUOTE = 900
ELLIPSIS_GAP = 240          # characters of the section an ellipsis may stand for
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\]|\[…\])\s*")
_SINGLE = re.compile(r"(?<![A-Za-z0-9])'([^'\n]{12,600})'(?![A-Za-z0-9.])")
_ITALIC = re.compile(r"(?<![A-Za-z0-9*_])(\*|_)(?![\s*_])([^*_\n]{12,600}?)(?<![\s*_])\1(?![A-Za-z0-9*_])")


def _norm(s: str) -> str:
    """Text as it is compared: compatibility forms folded (the ligatures and odd spaces a PDF carries), soft hyphens
    and zero-width marks dropped, every kind of hyphen and quote mark made plain, emphasis marks dropped, whitespace
    collapsed, lower case."""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub("[­​‌‍⁠﻿]", "", s)
    s = re.sub("[‐‑‒–—−]", "-", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace(" ", " ")
    s = re.sub(r"[*_`]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _parts(quote: str) -> list[str]:
    return [p for p in (x.strip(" .,;:!?\"'") for x in _ELLIPSIS.split(_norm(quote))) if p]


def quote_in(quote: str, text: str) -> bool:
    """A quote is in a section when it appears there, whitespace, quote marks and typography aside; punctuation at its
    ends is not held against it. An ellipsis may stand for a short stretch of the section (ELLIPSIS_GAP characters), and
    what is on each side of it must be a phrase of three words or more: a few single words in the right order, picked
    from across a section, can be made to say anything."""
    hay = _norm(text)
    parts = _parts(quote)
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in hay
    if any(len(p.split()) < 3 for p in parts):
        return False
    start = hay.find(parts[0])
    while start >= 0:                                   # every place the first phrase occurs: the rest must follow closely
        pos, ok = start + len(parts[0]), True
        for p in parts[1:]:
            i = hay.find(p, pos, pos + ELLIPSIS_GAP + len(p))
            if i < 0:
                ok = False; break
            pos = i + len(p)
        if ok:
            return True
        start = hay.find(parts[0], start + 1)
    return False


def _quoted(flat: str) -> list[tuple[int, str, str]]:
    """Every quoted span of a paragraph as (position, text, how): double quotes paired properly, then single-quoted
    and italic passages. Code spans are left out first: a name in backticks is not a quotation.
    Straight double quotes pair off in order (first opens, second closes); a curly opening quote runs to the next
    closing mark. So a short quoted word before a passage can no longer shift which marks belong together."""
    text = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), flat)
    out, taken = [], []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in '"“':
            j = i + 1
            while j < n and text[j] not in ('"”' if ch == "“" else '"') and text[j] != "\n":
                j += 1
            if j < n and text[j] != "\n":
                if 0 < j - i - 1 <= MAX_QUOTE:
                    out.append((i, text[i + 1:j], "double")); taken.append((i, j))
                i = j + 1
                continue
        i += 1
    free = lambda a, b: not any(a < e and s < b for s, e in taken)
    for rx, grp, how in ((_SINGLE, 1, "single"), (_ITALIC, 2, "italic")):
        for m in rx.finditer(text):
            if free(m.start(), m.end()) and len(m.group(grp).split()) >= 4:          # a passage, not a name or a stressed word
                out.append((m.start(), m.group(grp), how)); taken.append((m.start(), m.end()))
    return sorted(out)


def check_quotes(answer: str, sections: dict[str, dict]) -> list[dict]:
    """Every quoted passage that sits beside a section id in the answer, looked for in that section's text.
    `sections` maps a section id the tools handed this conversation to its row. A quote belongs to the next section id
    that follows it in the same paragraph (or to the one just before it when none follows).

    Each result says `found` and `checked`. A passage in double quotes (or a blockquote) of some length is checked:
    found, or not found and flagged. What cannot be told apart from ordinary writing (a word or two in quotes, a
    single-quoted or italic phrase) is looked for too: when it is in the section it is found; when it is not, it is
    left unchecked, shown as unchecked, and never counted as verified."""
    out = []
    for para in re.split(r"\n\s*\n", answer or ""):
        if not SECTION_ID.search(para):
            continue
        flat = re.sub(r"(?m)^\s*>\s?", "", para)
        ids = [(m.start(), m.group(0)) for m in SECTION_ID.finditer(flat)]
        quotes = _quoted(flat)
        if not quotes and para.lstrip().startswith(">"):                       # a blockquote with no quote marks: the quoted lines are the passage
            body = SECTION_ID.sub("", flat)
            body = re.sub(r"[`()\[\]]", "", body).strip(" -:\n")
            if len(body) >= 12:
                quotes = [(0, body, "double")]
        for pos, q, how in quotes:
            after = next((sid for p, sid in ids if p > pos), None) or ids[-1][1]
            sec = sections.get(after)
            found = bool(sec and quote_in(q, sec["text"]))
            passage = how == "double" and len(q.strip()) >= 12 and len(q.split()) >= 3
            out.append({"section": after, "quote": q.strip(), "found": found, "known": sec is not None, "checked": found or passage})
    return out


def passage_context(text: str, quote: str, span: int = 260) -> dict:
    """The text around a quote, for the source card: what comes before and after it in the section."""
    plain = re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", text)).strip()            # the section as _norm sees it, case kept
    parts = _parts(quote)
    hay = _norm(plain)
    if not parts or len(hay) != len(plain):
        return {"before": "", "after": ""}
    start = hay.find(parts[0])
    if start < 0:
        return {"before": "", "after": ""}
    end, pos = start, start
    for p in parts:
        i = hay.find(p, pos)
        if i < 0:
            break
        end = pos = i + len(p)
    while end < len(plain) and plain[end] in ".,;:!?\"'”":                         # the quote's own closing punctuation stays with it
        end += 1
    before, after = plain[max(0, start - span): start], plain[end: end + span]
    if start > span:
        before = re.sub(r"^\S*\s", "", before)
    if len(plain) > end + span:
        after = re.sub(r"\s\S*$", "", after)
    return {"before": before.strip(), "after": after.strip()}
