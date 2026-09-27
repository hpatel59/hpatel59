"""Export the transcribed textbook questions (../data/s*.py) to content/questions.json,
with textbook diagrams cropped from the PDF into content/img/*.png.

    AL_PDF=/path/to/book.pdf python3 export_content.py

content/ reproduces copyrighted textbook material, so it is not committed.
"""
import importlib, io, json, os, sys

import pymupdf
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from chapters import SECTIONS  # noqa: E402

OUT = os.path.join(HERE, "content")
PDF = os.environ.get("AL_PDF", os.path.join(ROOT, "A Level Computer Science Digital Text Book.pdf"))
# OCR H446 paper each textbook section is examined on
PAPER = {s: (1 if s <= 9 else 2) for s in SECTIONS}
BLOCK_KEYS = ("text", "ctx", "code", "table", "pre", "after", "draw", "box", "marks", "lines")

_pdf = None


def crop(page, rect, name):
    """Save a diagram from the scanned PDF as a small greyscale PNG; returns [file, w, h]."""
    global _pdf
    if _pdf is None:
        _pdf = pymupdf.open(PDF)
    pix = _pdf[page].get_pixmap(dpi=130, clip=pymupdf.Rect(*rect), colorspace=pymupdf.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    im = im.point(lambda v: 255 if v > 215 else v * 255 // 215)
    im = im.quantize(8, dither=Image.Dither.NONE)
    fn = f"{name}.png"
    im.save(os.path.join(OUT, "img", fn), "PNG", optimize=True)
    return [fn, im.width, im.height]


def block(b, qid):
    out = {k: b[k] for k in BLOCK_KEYS if b.get(k) not in (None, "")}
    if b.get("img"):
        pg, rect, _ = b["img"]
        out["img"] = crop(pg, rect, qid)
    return out


def main():
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    sections, questions = [], []
    for s in sorted(SECTIONS):
        doc = importlib.import_module(f"data.s{s}").DOC
        sections.append({"n": s, "title": doc["title"], "paper": PAPER[s],
                         "chapters": [{"n": c, "title": t} for c, t in doc["chapters"]]})
        for kind, key in (("q", "questions"), ("e", "exercises")):
            for q in doc[key]:
                qid = f"{s}-{kind}-{q['ch']}-{q['n']}"
                item = {"id": qid, "section": s, "kind": kind, "ch": q["ch"], "n": q["n"],
                        "page": q.get("page"), **block(q, qid)}
                if q.get("parts"):
                    item["parts"] = [dict(label=p.get("label", ""), **block(p, f"{qid}-{i}"))
                                     for i, p in enumerate(q["parts"])]
                item["total"] = (q.get("marks") or 0) + sum(p.get("marks") or 0 for p in q.get("parts", []))
                questions.append(item)
    with open(os.path.join(OUT, "questions.json"), "w", encoding="utf-8") as f:
        json.dump({"sections": sections, "questions": questions}, f, ensure_ascii=False)
    n_img = len(os.listdir(os.path.join(OUT, "img")))
    print(f"{len(questions)} questions, {n_img} images -> {OUT}")


if __name__ == "__main__":
    main()
