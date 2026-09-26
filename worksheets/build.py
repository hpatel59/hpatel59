"""Build OCR J277 pupil worksheets (Google-Docs-ready HTML) from the textbook data.

Two documents per unit:
  * In-chapter questions (the yellow Q boxes), grouped by topic
  * End of unit exercises
Each has a DIGITAL version (pupils type in the boxes) and a PRINT version
(bigger writing spaces). Output goes to worksheets/out/*.html; each file is
uploaded to Google Drive, which converts it to a Google Doc.
"""
import base64, html, io, os, sys, importlib

import pymupdf
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PDF = os.environ.get("J277_PDF", "OCR Computer Science Textbook.pdf")

NAVY = "#1f3864"
TOPIC_BG = "#dae3f3"
CODE_BG = "#f2f2f2"
HEAD_BG = "#d9d9d9"

_pdf = None

CSS = ("body{font-family:Arial;font-size:11pt}"
       "table{border-collapse:collapse}"
       "td.c{border:1px solid #7f7f7f;padding:4pt;vertical-align:top}"
       "td.m{border:1px solid #7f7f7f;padding:4pt;vertical-align:top;text-align:center}"
       "td.h{border:1px solid #7f7f7f;padding:4pt;background-color:#d9d9d9;font-weight:bold;text-align:center}"
       "td.t{border:1px solid #7f7f7f;padding:4pt;background-color:#dae3f3;font-weight:bold}"
       "td.a{border:1px solid #1f3864;padding:5pt;vertical-align:top}"
       "td.k{border:1px solid #bfbfbf;background-color:#f2f2f2;padding:5pt}"
       "p.k{font-family:Courier New;font-size:10pt}"
       "p.l{color:#7f7f7f;font-size:9pt}"
       "td.b{background-color:#1f3864;padding:5pt}span.b{color:#ffffff;font-size:13pt;font-weight:bold}"
       "b.q{color:#1f3864}span.mk{color:#595959}span.s{color:#7f7f7f;font-size:9pt}"
       "p.lk{color:#2e75b6;font-size:9pt}p.cx{color:#595959;font-style:italic}"
       "p.sr{text-align:right;color:#7f7f7f;font-size:9pt;font-style:italic}p.pt{margin-left:18pt}")


def crop_img(page, rect, width_pt, dpi=110):
    """Crop a diagram from the textbook PDF and return an <img> tag (1-bit PNG data URI)."""
    global _pdf
    if _pdf is None:
        _pdf = pymupdf.open(PDF)
    pix = _pdf[page - 1].get_pixmap(dpi=dpi, clip=pymupdf.Rect(*rect),
                                    colorspace=pymupdf.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    im = im.point(lambda v: 255 if v > 200 else 0).convert("1")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    height = round(width_pt * h / w)
    return (f'<p><img src="data:image/png;base64,{b64}" '
            f'width="{round(width_pt*4/3)}" height="{round(height*4/3)}"></p>')


def esc(s):
    """Escape text but allow a tiny markup: **bold**, `code`."""
    s = html.escape(s)
    out, bold, code = [], False, False
    i = 0
    while i < len(s):
        if s.startswith("**", i):
            out.append("</b>" if bold else "<b>")
            bold = not bold
            i += 2
        elif s[i] == "`":
            out.append("</span>" if code else '<span style="font-family:Courier New">')
            code = not code
            i += 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out).replace("\n", "<br>")


def cell(content, bg=None, bold=False, width=None, align="left"):
    cls = "h" if bg == HEAD_BG else ("t" if bg == TOPIC_BG else "c")
    if align == "center" and cls == "c":
        cls = "m"
    w = f' width="{round(width*4/3)}"' if width else ""
    c = esc(content) if content else "&nbsp;"
    if bold and cls == "c":
        c = f"<b>{c}</b>"
    return f'<td class="{cls}"{w}>{c}</td>'


def answer_box(lines, label="Answer"):
    body = f'<p class="l">{label}:</p>' + "<p>&nbsp;</p>" * lines
    return f'<table><tr><td class="a" width="624">{body}</td></tr></table><p>&nbsp;</p>'


def draw_box(lines, print_mode):
    label = ("Draw your answer here" if print_mode else
             "Draw your answer here (Google Docs: Insert → Drawing → + New), "
             "or type/describe it")
    return answer_box(lines, label)


def code_block(code):
    body = "".join(
        f'<p class="k">{html.escape(l).replace(" ", "&nbsp;") or "&nbsp;"}</p>'
        for l in code.strip("\n").split("\n"))
    return f'<table><tr><td class="k">{body}</td></tr></table><p>&nbsp;</p>'


def data_table(t, print_mode=False):
    """t = dict(header=[...], rows=[[...]], width=pt, caption=str).
    Empty strings are blank editable cells. Column widths are set on the first row only."""
    rows = []
    hdr = t.get("header")
    ncol = len(hdr) if hdr else len(t["rows"][0])
    w = t.get("width", min(468, 80 * ncol))
    cw = round(w / ncol)
    cols = t.get("cols") or [cw] * ncol
    # in the print version give blank cells room for handwriting (not for tick boxes)
    tall = print_mode and not t.get("short") and (ncol <= 4 or cw < 60)
    blank = "&nbsp;<br>&nbsp;" if tall else "&nbsp;"
    first = True
    if hdr:
        rows.append("<tr>" + "".join(cell(h, HEAD_BG, True, cols[i], "center") for i, h in enumerate(hdr)) + "</tr>")
        first = False
    for r in t["rows"]:
        cls = "m" if t.get("align", "center") == "center" else "c"
        tds = []
        for i, c in enumerate(r):
            wa = f' width="{round(cols[i]*4/3)}"' if first else ""
            tds.append(f'<td class="{cls}"{wa}>{esc(c) if c else blank}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
        first = False
    cap = f'<p><i>{esc(t["caption"])}</i></p>' if t.get("caption") else ""
    return cap + '<table>' + "".join(rows) + "</table><p>&nbsp;</p>"


def n_lines(marks, lines, print_mode):
    if lines is None:
        lines = 3 if not marks else min(10, marks + 1)
    return max(3, round(lines * 2)) if print_mode else lines


def render_block(b, print_mode):
    """Common bits of a question or a question part."""
    h = []
    if b.get("ctx"):
        h.append(f'<p class="cx">{esc(b["ctx"])}</p>')
    if b.get("img"):
        pg, rect, w = b["img"]
        h.append(crop_img(pg, rect, w))
    if b.get("code"):
        h.append(code_block(b["code"]))
    if b.get("table"):
        h.append(data_table(b["table"], print_mode))
    if b.get("pre"):
        h.append(f"<p>{esc(b['pre'])}</p>")
    if b.get("draw"):
        h.append(draw_box(n_lines(b.get("marks"), b.get("lines", 8), print_mode), print_mode))
    elif b.get("box", True):
        label = "Working / notes" if b.get("table") and any("" in r for r in b["table"]["rows"]) else "Answer"
        h.append(answer_box(n_lines(b.get("marks"), b.get("lines"), print_mode), label))
    if b.get("after"):
        h.append(f'<p class="sr">{esc(b["after"])}</p>')
    return "".join(h)


def marks_txt(m):
    return f' <span class="mk">[{m}]</span>' if m else ""


def render_q(q, print_mode):
    h = []
    src = f' <span class="s">(textbook p.{q["page"]})</span>' if q.get("page") else ""
    link = (f'<p class="lk">Links to topic(s): {esc(q["links"])}</p>'
            if q.get("links") else "")
    text = q.get("print_text", q["text"]) if print_mode else q["text"]
    h.append(f'<p><b class="q">Q{q["n"]}</b>&nbsp;&nbsp;{esc(text)}'
             f'{marks_txt(q.get("marks"))}{src}</p>{link}')
    if q.get("parts"):
        # the stem may carry context / code / table / image but no answer box
        stem = dict(q, box=False, draw=False)
        h.append(render_block(stem, print_mode))
        for p in q["parts"]:
            if p["label"] or p["text"]:
                lab = p["label"] if "(" in p["label"] else "(" + p["label"] + ")"
                h.append(f'<p class="pt"><b>{lab}</b>&nbsp;&nbsp;'
                         f'{esc(p["text"])}{marks_txt(p.get("marks"))}</p>')
            h.append(render_block(p, print_mode))
    else:
        h.append(render_block(q, print_mode))
    return "".join(h)


def header(doc, kind_title, print_mode):
    ver = "PRINT VERSION" if print_mode else "DIGITAL VERSION – type your answers in the boxes"
    topics = ", ".join(f"{t} {n}" for t, n in doc["topics"])
    info = [
        ("Course", "OCR GCSE (9–1) Computer Science J277"),
        ("Unit", f'Unit {doc["unit"]}: {doc["title"]}'),
        ("Paper", doc["paper"]),
        ("Worksheet", kind_title),
        ("Topics", topics),
    ]
    rows = "".join(f"<tr>{cell(a, TOPIC_BG, True, 90)}{cell(b, None, False, 378)}</tr>" for a, b in info)
    pupil = ('<table><tr>'
             + cell("Name:", None, True, 156) + cell("Class:", None, True, 156)
             + cell("Date:", None, True, 156) + "</tr></table>")
    return (f'<h1 style="color:{NAVY};font-family:Arial">Unit {doc["unit"]} – {esc(kind_title)}</h1>'
            f'<p style="color:#c00000"><b>{ver}</b></p>'
            f'<table>{rows}</table><p>&nbsp;</p>{pupil}<p>&nbsp;</p>')


def build(doc, kind, print_mode):
    if kind == "q":
        kind_title = "In-chapter Questions (by topic)"
        intro = ("These are the questions from the yellow boxes in each topic of your textbook. "
                 "Answer each question in the box underneath it.")
    else:
        kind_title = "End of Unit Exercises"
        intro = ("These are the exam-style exercises from the end of the unit in your textbook. "
                 "The topic each question links to is shown under it. Marks are in [square brackets].")
    h = ['<html><head><style>' + CSS + '</style></head><body>', header(doc, kind_title, print_mode),
         f"<p><i>{intro}</i></p>"]
    items = doc["questions"] if kind == "q" else doc["exercises"]
    cur = None
    for q in items:
        if kind == "q" and q["topic"] != cur:
            cur = q["topic"]
            name = dict(doc["topics"])[cur]
            h.append(f'<table><tr><td class="b" width="624"><span class="b">Topic {cur} \u2013 {esc(name)}</span>'
                     '</td></tr></table><p>&nbsp;</p>')
        h.append(render_q(q, print_mode))
    total = sum((q.get("marks") or 0) + sum(p.get("marks") or 0 for p in q.get("parts", []))
                for q in items)
    if kind == "e" and total:
        h.append(f'<p style="text-align:right"><b>Total: ______ / {total} marks</b></p>')
    h.append("</body></html>")
    return "".join(h)


def main(units):
    os.makedirs(OUT, exist_ok=True)
    for u in units:
        doc = importlib.import_module(f"data.unit{u}").DOC
        for kind in ("q", "e"):
            for pm in (False, True):
                fn = f'U{u}_{"Questions" if kind == "q" else "Exercises"}_{"PRINT" if pm else "DIGITAL"}.html'
                html_out = build(doc, kind, pm)
                # one block per line so the files are easy to read and diff
                for tag in ("</p>", "</table>", "</tr>"):
                    html_out = html_out.replace(tag, tag + "\n")
                with open(os.path.join(OUT, fn), "w") as f:
                    f.write(html_out)
                print(fn, os.path.getsize(os.path.join(OUT, fn)))


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    main([int(a) for a in sys.argv[1:]] or range(1, 9))
