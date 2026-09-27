"""Revision app for OCR A Level Computer Science students.

Students sign in with an anonymous avatar + PIN, answer the textbook questions, and get AI marking,
feedback, hints and practice questions. The teacher dashboard shows class progress and every answer.

Environment:
  ANTHROPIC_API_KEY   school API key (required for AI features)
  TEACHER_PASSWORD    password for the teacher dashboard (required)
  SECRET_KEY          random string used to sign session cookies (optional: generated and kept in DATA_DIR)
  DATA_DIR            where the SQLite database and uploads live (default ./instance)
  MODEL               Claude model (default claude-opus-5)
  DAILY_LIMIT         AI requests per student per day (default 60)
"""
import csv, hmac, io, json, os, secrets, sqlite3, time
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import wraps

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory, session
from PIL import Image

import ai
from avatars import generate

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "instance"))
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOADS = os.path.join(DATA_DIR, "uploads")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "60"))
MAX_ANSWER = 6000
# rough cost per million tokens, for the usage panel only (claude-opus-5 list price)
PRICE_IN, PRICE_OUT = float(os.environ.get("PRICE_IN", "5")), float(os.environ.get("PRICE_OUT", "25"))

def secret_key():
    """SECRET_KEY from the environment, else one generated once and kept in DATA_DIR (so sign-ins
    survive restarts and are shared by every worker process)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "secret_key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(SECRET_KEY=secret_key(),
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                  MAX_CONTENT_LENGTH=25 * 1024 * 1024)
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "")

with open(os.path.join(HERE, "content", "questions.json"), encoding="utf-8") as f:
    CONTENT = json.load(f)
QUESTIONS = {q["id"]: q for q in CONTENT["questions"]}
CHAPTERS = {c["n"]: dict(c, section=s["n"]) for s in CONTENT["sections"] for c in s["chapters"]}

SCHEMA = """
CREATE TABLE IF NOT EXISTS avatars (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, pin TEXT NOT NULL,
  disabled INTEGER DEFAULT 0, created TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, avatar_id INTEGER NOT NULL, qid TEXT NOT NULL,
  answer TEXT, result TEXT, score INTEGER, max INTEGER, after_reveal INTEGER DEFAULT 0,
  teacher_score INTEGER, teacher_comment TEXT, flagged INTEGER DEFAULT 0, flag_note TEXT,
  flag_resolved INTEGER DEFAULT 0, created TEXT);
CREATE INDEX IF NOT EXISTS attempts_av ON attempts(avatar_id, qid);
CREATE TABLE IF NOT EXISTS reveals (avatar_id INTEGER, qid TEXT, PRIMARY KEY (avatar_id, qid));
CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, avatar_id INTEGER, qid TEXT, role TEXT,
  content TEXT, flagged INTEGER DEFAULT 0, flag_note TEXT, flag_resolved INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS practice (id INTEGER PRIMARY KEY, avatar_id INTEGER, source_qid TEXT,
  question TEXT, marks INTEGER, topic TEXT, answer TEXT, result TEXT, score INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS plans (avatar_id INTEGER PRIMARY KEY, plan TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, avatar_id INTEGER, kind TEXT, input INTEGER,
  output INTEGER, day TEXT);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    os.makedirs(UPLOADS, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM avatars LIMIT 1").fetchone():
        for path in (os.path.join(DATA_DIR, "avatars.csv"), os.path.join(HERE, "avatars.csv")):
            if os.path.exists(path):
                with open(path, newline="") as f:
                    rows = [(r["avatar"], r["pin"], now()) for r in csv.DictReader(f) if r.get("avatar")]
                conn.executemany("INSERT OR IGNORE INTO avatars (name, pin, created) VALUES (?,?,?)", rows)
                break
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- auth helpers

_fails = defaultdict(list)


def throttled(key):
    t = time.time()
    _fails[key] = [x for x in _fails[key] if t - x < 600]
    return len(_fails[key]) >= 10


def student_required(fn):
    @wraps(fn)
    def wrap(*a, **k):
        aid = session.get("avatar_id")
        if not aid:
            return jsonify(error="Please sign in."), 401
        row = db().execute("SELECT * FROM avatars WHERE id=? AND disabled=0", (aid,)).fetchone()
        if not row:
            session.clear()
            return jsonify(error="This avatar is no longer active."), 401
        g.avatar = row
        return fn(*a, **k)
    return wrap


def teacher_required(fn):
    @wraps(fn)
    def wrap(*a, **k):
        if not session.get("teacher"):
            return jsonify(error="Teacher sign-in required."), 401
        return fn(*a, **k)
    return wrap


def ai_budget_ok():
    n = db().execute("SELECT COUNT(*) FROM usage WHERE avatar_id=? AND day=?",
                     (g.avatar["id"], date.today().isoformat())).fetchone()[0]
    return n < DAILY_LIMIT


def log_usage(kind, u):
    db().execute("INSERT INTO usage (avatar_id, kind, input, output, day) VALUES (?,?,?,?,?)",
                 (g.avatar["id"], kind, u["input"], u["output"], date.today().isoformat()))


def ai_error(msg, code=502):
    return jsonify(error=msg), code


LIMIT_MSG = (f"You've used today's {DAILY_LIMIT} AI requests. They reset tomorrow - "
             "meanwhile, review your feedback or redo a question on paper.")


# ---------------------------------------------------------------- pages and content

@app.get("/")
def index():
    return send_from_directory(HERE + "/static", "index.html")


@app.get("/img/<path:fn>")
def img(fn):
    if not (session.get("avatar_id") or session.get("teacher")):
        abort(401)
    return send_from_directory(os.path.join(HERE, "content", "img"), fn, max_age=86400)


@app.get("/uploads/<path:fn>")
@teacher_required
def uploads(fn):
    return send_from_directory(UPLOADS, fn)


@app.get("/api/content")
def content():
    if not (session.get("avatar_id") or session.get("teacher")):
        return jsonify(error="Please sign in."), 401
    return jsonify(CONTENT)


# ---------------------------------------------------------------- student auth

@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    if throttled(ip):
        return jsonify(error="Too many attempts. Wait 10 minutes and try again."), 429
    d = request.get_json(silent=True) or {}
    name, pin = (d.get("avatar") or "").strip(), (d.get("pin") or "").strip()
    row = db().execute("SELECT * FROM avatars WHERE lower(name)=lower(?) AND disabled=0", (name,)).fetchone()
    if not row or not hmac.compare_digest(row["pin"], pin):
        _fails[ip].append(time.time())
        return jsonify(error="That avatar name and PIN don't match. Check your card and try again."), 401
    session.clear()
    session.permanent = True
    session["avatar_id"] = row["id"]
    db().execute("UPDATE avatars SET last_seen=? WHERE id=?", (now(), row["id"]))
    db().commit()
    return jsonify(avatar=row["name"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    if session.get("teacher"):
        return jsonify(teacher=True)
    aid = session.get("avatar_id")
    row = aid and db().execute("SELECT name FROM avatars WHERE id=? AND disabled=0", (aid,)).fetchone()
    if not row:
        return jsonify(avatar=None)
    used = db().execute("SELECT COUNT(*) FROM usage WHERE avatar_id=? AND day=?",
                        (aid, date.today().isoformat())).fetchone()[0]
    return jsonify(avatar=row["name"], ai_left=max(0, DAILY_LIMIT - used), ai_limit=DAILY_LIMIT)


# ---------------------------------------------------------------- progress

def best_scores(avatar_id):
    """{qid: {"best": n, "max": n, "attempts": n, "last": iso, "teacher": bool}} using teacher overrides."""
    out = {}
    for r in db().execute("SELECT qid, score, max, teacher_score, created FROM attempts WHERE avatar_id=? "
                          "ORDER BY id", (avatar_id,)):
        s = r["teacher_score"] if r["teacher_score"] is not None else r["score"]
        o = out.setdefault(r["qid"], {"best": 0, "max": r["max"], "attempts": 0, "last": None})
        o["best"] = max(o["best"], s or 0)
        o["max"] = r["max"]
        o["attempts"] += 1
        o["last"] = r["created"]
    return out


def chapter_stats(best):
    stats = {}
    for c in CHAPTERS:
        qs = [q for q in CONTENT["questions"] if q["ch"] == c]
        done = [best[q["id"]] for q in qs if q["id"] in best]
        got, mx = sum(d["best"] for d in done), sum(d["max"] for d in done)
        stats[c] = {"total": len(qs), "done": len(done), "score": got, "max": mx,
                    "pct": round(100 * got / mx) if mx else None}
    return stats


@app.get("/api/progress")
@student_required
def progress():
    best = best_scores(g.avatar["id"])
    recent = [dict(qid=r["qid"], score=r["teacher_score"] if r["teacher_score"] is not None else r["score"],
                   max=r["max"], created=r["created"])
              for r in db().execute("SELECT * FROM attempts WHERE avatar_id=? ORDER BY id DESC LIMIT 8",
                                    (g.avatar["id"],))]
    days = {r[0][:10] for r in db().execute("SELECT created FROM attempts WHERE avatar_id=?", (g.avatar["id"],))}
    d = date.today()
    if d.isoformat() not in days:  # a streak survives until the end of the next day
        d = date.fromordinal(d.toordinal() - 1)
    streak = 0
    while d.isoformat() in days:
        streak += 1
        d = date.fromordinal(d.toordinal() - 1)
    plan = db().execute("SELECT plan, created FROM plans WHERE avatar_id=?", (g.avatar["id"],)).fetchone()
    return jsonify(best=best, chapters=chapter_stats(best), recent=recent, streak=streak,
                   plan=json.loads(plan["plan"]) | {"created": plan["created"]} if plan else None)


@app.get("/api/question/<qid>")
@student_required
def question_state(qid):
    if qid not in QUESTIONS:
        abort(404)
    aid = g.avatar["id"]
    attempts = [dict(id=r["id"], answer=json.loads(r["answer"]), result=json.loads(r["result"]),
                     score=r["score"], max=r["max"], after_reveal=r["after_reveal"],
                     teacher_score=r["teacher_score"], teacher_comment=r["teacher_comment"], created=r["created"])
                for r in db().execute("SELECT * FROM attempts WHERE avatar_id=? AND qid=? ORDER BY id", (aid, qid))]
    revealed = bool(db().execute("SELECT 1 FROM reveals WHERE avatar_id=? AND qid=?", (aid, qid)).fetchone())
    chat = [dict(role=r["role"], content=r["content"]) for r in
            db().execute("SELECT role, content FROM chats WHERE avatar_id=? AND qid=? AND role IN ('user','assistant') "
                        "ORDER BY id", (aid, qid))]
    prac = [dict(id=r["id"], question=r["question"], marks=r["marks"], topic=r["topic"],
                 answer=r["answer"], result=json.loads(r["result"]) if r["result"] else None)
            for r in db().execute("SELECT * FROM practice WHERE avatar_id=? AND source_qid=? ORDER BY id", (aid, qid))]
    for a in attempts:  # model answers stay hidden until the student chooses to see them
        if not revealed:
            for p in a["result"].get("parts", []):
                p.pop("model_answer", None)
    return jsonify(attempts=attempts, revealed=revealed, chat=chat, practice=prac)


def save_upload(fs):
    """Validate and shrink an uploaded photo; returns (jpeg_bytes, 'image/jpeg', filename)."""
    try:
        im = Image.open(fs.stream)
        im.load()
    except Exception:
        raise ValueError("That file isn't an image we can read. Upload a JPG or PNG photo.")
    im = im.convert("RGB")
    im.thumbnail((1500, 1500))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    fn = f"{g.avatar['id']}-{int(time.time()*1000)}-{secrets.token_hex(3)}.jpg"
    with open(os.path.join(UPLOADS, fn), "wb") as f:
        f.write(buf.getvalue())
    return buf.getvalue(), "image/jpeg", fn


@app.post("/api/question/<qid>/submit")
@student_required
def submit(qid):
    q = QUESTIONS.get(qid) or abort(404)
    if not ai_budget_ok():
        return ai_error(LIMIT_MSG, 429)
    try:
        answers = json.loads(request.form.get("answers") or "{}")
    except json.JSONDecodeError:
        return jsonify(error="Your answer couldn't be read. Try again."), 400
    for a in answers.values():
        if len(a.get("text") or "") > MAX_ANSWER or any(len(v) > 500 for v in (a.get("cells") or {}).values()):
            return jsonify(error="That answer is too long. Keep each part under 6,000 characters."), 400
    uploads, files = {}, {}
    for key, fs in request.files.items():
        if key.startswith("photo_") and fs.filename:
            try:
                data, mime, fn = save_upload(fs)
            except ValueError as e:
                return jsonify(error=str(e)), 400
            uploads[key[6:]] = (data, mime)
            files[key[6:]] = fn
    if not any((a.get("text") or "").strip() or any((a.get("cells") or {}).values()) for a in answers.values()) \
            and not uploads:
        return jsonify(error="Write an answer first."), 400
    try:
        result, u = ai.mark(q, CHAPTERS[q["ch"]]["title"], answers, uploads)
    except ai.AIError as e:
        return ai_error(str(e))
    log_usage("mark", u)
    aid = g.avatar["id"]
    revealed = bool(db().execute("SELECT 1 FROM reveals WHERE avatar_id=? AND qid=?", (aid, qid)).fetchone())
    for k, fn in files.items():
        answers.setdefault(k, {})["photo"] = fn
    cur = db().execute(
        "INSERT INTO attempts (avatar_id, qid, answer, result, score, max, after_reveal, flagged, flag_note, created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (aid, qid, json.dumps(answers), json.dumps(result), result["score"], result["max"], int(revealed),
         int(bool(result.get("safeguarding_concern"))), result.get("safeguarding_note") or "", now()))
    db().commit()
    if not revealed:
        for p in result["parts"]:
            p.pop("model_answer", None)
    for k in ("safeguarding_concern", "safeguarding_note"):
        result.pop(k, None)
    return jsonify(id=cur.lastrowid, result=result, after_reveal=revealed)


@app.post("/api/question/<qid>/reveal")
@student_required
def reveal(qid):
    if qid not in QUESTIONS:
        abort(404)
    aid = g.avatar["id"]
    if not db().execute("SELECT 1 FROM attempts WHERE avatar_id=? AND qid=?", (aid, qid)).fetchone():
        return jsonify(error="Have a go first - model answers unlock after your first marked attempt."), 400
    db().execute("INSERT OR IGNORE INTO reveals VALUES (?,?)", (aid, qid))
    db().commit()
    return question_state(qid)


@app.post("/api/question/<qid>/chat")
@student_required
def chat(qid):
    q = QUESTIONS.get(qid) or abort(404)
    msg = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not msg:
        return jsonify(error="Type a question for the tutor."), 400
    if len(msg) > 1500:
        return jsonify(error="Keep your message under 1,500 characters."), 400
    if not ai_budget_ok():
        return ai_error(LIMIT_MSG, 429)
    aid = g.avatar["id"]
    hist = [dict(role=r["role"], content=r["content"]) for r in
            db().execute("SELECT role, content FROM chats WHERE avatar_id=? AND qid=? AND role IN ('user','assistant') "
                        "ORDER BY id DESC LIMIT 12",
                         (aid, qid))][::-1]
    while hist and hist[0]["role"] != "user":
        hist.pop(0)
    hist.append({"role": "user", "content": msg})
    last = db().execute("SELECT result FROM attempts WHERE avatar_id=? AND qid=? ORDER BY id DESC LIMIT 1",
                        (aid, qid)).fetchone()
    last_result = json.loads(last["result"]) if last else None
    if last_result:
        last_result = {k: last_result[k] for k in ("parts", "score", "max") if k in last_result}
    try:
        data, u = ai.tutor(q, CHAPTERS[q["ch"]]["title"], hist, bool(last), last_result)
    except ai.AIError as e:
        return ai_error(str(e))
    log_usage("tutor", u)
    flag = bool(data.get("safeguarding_concern"))
    db().execute("INSERT INTO chats (avatar_id, qid, role, content, flagged, flag_note, created) VALUES (?,?,?,?,?,?,?)",
                 (aid, qid, "user", msg, int(flag), data.get("safeguarding_note") or "", now()))
    db().execute("INSERT INTO chats (avatar_id, qid, role, content, created) VALUES (?,?,?,?,?)",
                 (aid, qid, "assistant", data["reply"], now()))
    db().commit()
    return jsonify(reply=data["reply"])


@app.post("/api/question/<qid>/practice")
@student_required
def new_practice(qid):
    q = QUESTIONS.get(qid) or abort(404)
    if not ai_budget_ok():
        return ai_error(LIMIT_MSG, 429)
    try:
        data, u = ai.practice(q, CHAPTERS[q["ch"]]["title"])
    except ai.AIError as e:
        return ai_error(str(e))
    log_usage("practice", u)
    marks = max(1, min(8, int(data.get("marks") or 3)))
    cur = db().execute("INSERT INTO practice (avatar_id, source_qid, question, marks, topic, created) VALUES (?,?,?,?,?,?)",
                       (g.avatar["id"], qid, data["question"], marks, data.get("topic", ""), now()))
    db().commit()
    return jsonify(id=cur.lastrowid, question=data["question"], marks=marks, topic=data.get("topic", ""))


@app.post("/api/practice/<int:pid>/submit")
@student_required
def submit_practice(pid):
    row = db().execute("SELECT * FROM practice WHERE id=? AND avatar_id=?", (pid, g.avatar["id"])).fetchone()
    if not row:
        abort(404)
    text = ((request.get_json(silent=True) or {}).get("answer") or "").strip()
    if not text:
        return jsonify(error="Write an answer first."), 400
    if len(text) > MAX_ANSWER:
        return jsonify(error="That answer is too long."), 400
    if not ai_budget_ok():
        return ai_error(LIMIT_MSG, 429)
    src = QUESTIONS[row["source_qid"]]
    pq = {"id": f"p{pid}", "ch": src["ch"], "text": row["question"], "marks": row["marks"]}
    try:
        result, u = ai.mark(pq, CHAPTERS[src["ch"]]["title"], {"0": {"text": text}}, {})
    except ai.AIError as e:
        return ai_error(str(e))
    log_usage("mark", u)
    if result.get("safeguarding_concern"):
        db().execute("INSERT INTO chats (avatar_id, qid, role, content, flagged, flag_note, created) "
                     "VALUES (?,?,?,?,?,?,?)", (g.avatar["id"], row["source_qid"], "practice", text, 1,
                                                result.get("safeguarding_note") or "", now()))
    for k in ("safeguarding_concern", "safeguarding_note"):
        result.pop(k, None)
    db().execute("UPDATE practice SET answer=?, result=?, score=? WHERE id=?",
                 (text, json.dumps(result), result["score"], pid))
    db().commit()
    return jsonify(result=result)


@app.post("/api/plan")
@student_required
def make_plan():
    if not ai_budget_ok():
        return ai_error(LIMIT_MSG, 429)
    aid = g.avatar["id"]
    best = best_scores(aid)
    stats = chapter_stats(best)
    chapters = [dict(chapter=c, title=CHAPTERS[c]["title"], section=CHAPTERS[c]["section"],
                     questions=s["total"], answered=s["done"], percent=s["pct"]) for c, s in stats.items()]
    mis = []
    for r in db().execute("SELECT qid, result FROM attempts WHERE avatar_id=? ORDER BY id DESC LIMIT 25", (aid,)):
        res = json.loads(r["result"])
        mis += [f"Ch {QUESTIONS[r['qid']]['ch']}: {m}" for m in res.get("misconceptions", [])]
    progress_data = {"chapters": [c for c in chapters if c["answered"]] or chapters[:6],
                     "not_started_chapters": [c["chapter"] for c in chapters if not c["answered"]],
                     "recent_misconceptions": mis[:30]}
    try:
        plan, u = ai.study_plan(progress_data)
    except ai.AIError as e:
        return ai_error(str(e))
    log_usage("plan", u)
    db().execute("INSERT OR REPLACE INTO plans VALUES (?,?,?)", (aid, json.dumps(plan), now()))
    db().commit()
    return jsonify(plan | {"created": now()})


# ---------------------------------------------------------------- teacher

@app.post("/api/teacher/login")
def teacher_login():
    ip = request.remote_addr or "?"
    if throttled("t" + ip):
        return jsonify(error="Too many attempts. Wait 10 minutes."), 429
    pw = (request.get_json(silent=True) or {}).get("password") or ""
    if not TEACHER_PASSWORD or not hmac.compare_digest(pw, TEACHER_PASSWORD):
        _fails["t" + ip].append(time.time())
        return jsonify(error="Wrong password." if TEACHER_PASSWORD else
                       "TEACHER_PASSWORD is not set on the server."), 401
    session.clear()
    session["teacher"] = True
    return jsonify(ok=True)


@app.get("/api/teacher/overview")
@teacher_required
def overview():
    avatars = db().execute("SELECT * FROM avatars ORDER BY name").fetchall()
    rows, class_ch = [], defaultdict(lambda: [0, 0, 0])
    for a in avatars:
        best = best_scores(a["id"])
        stats = chapter_stats(best)
        sec = defaultdict(lambda: [0, 0, 0])
        for c, s in stats.items():
            x = sec[CHAPTERS[c]["section"]]
            x[0] += s["score"]; x[1] += s["max"]; x[2] += s["done"]
            y = class_ch[c]
            y[0] += s["score"]; y[1] += s["max"]; y[2] += s["done"]
        attempts = sum(b["attempts"] for b in best.values())
        rows.append(dict(id=a["id"], name=a["name"], disabled=a["disabled"], last_seen=a["last_seen"],
                         answered=len(best), attempts=attempts,
                         sections={s: (round(100 * v[0] / v[1]) if v[1] else None, v[2]) for s, v in sec.items()}))
    chapters = [dict(ch=c, title=CHAPTERS[c]["title"], section=CHAPTERS[c]["section"],
                     pct=round(100 * v[0] / v[1]) if v[1] else None, answered=v[2]) for c, v in class_ch.items()]
    flags = db().execute("SELECT (SELECT COUNT(*) FROM attempts WHERE flagged=1 AND flag_resolved=0) + "
                         "(SELECT COUNT(*) FROM chats WHERE flagged=1 AND flag_resolved=0)").fetchone()[0]
    u = db().execute("SELECT COALESCE(SUM(input),0), COALESCE(SUM(output),0), COUNT(*) FROM usage").fetchone()
    t = db().execute("SELECT COALESCE(SUM(input),0), COALESCE(SUM(output),0), COUNT(*) FROM usage WHERE day=?",
                     (date.today().isoformat(),)).fetchone()
    cost = lambda r: round((r[0] * PRICE_IN + r[1] * PRICE_OUT) / 1e6, 2)
    return jsonify(avatars=rows, chapters=chapters, flags=flags, model=ai.MODEL, daily_limit=DAILY_LIMIT,
                   usage=dict(total_requests=u[2], total_cost=cost(u), today_requests=t[2], today_cost=cost(t)))


@app.get("/api/teacher/attempts")
@teacher_required
def teacher_attempts():
    sql, args = "SELECT t.*, a.name FROM attempts t JOIN avatars a ON a.id=t.avatar_id WHERE 1=1", []
    if request.args.get("avatar"):
        sql += " AND t.avatar_id=?"; args.append(int(request.args["avatar"]))
    if request.args.get("ch"):
        sql += " AND t.qid LIKE ?"; args.append(f"%-{int(request.args['ch'])}-%")
    if request.args.get("flagged"):
        sql += " AND t.flagged=1"
    sql += " ORDER BY t.id DESC LIMIT 200"
    out = [dict(id=r["id"], avatar=r["name"], avatar_id=r["avatar_id"], qid=r["qid"],
                answer=json.loads(r["answer"]), result=json.loads(r["result"]), score=r["score"], max=r["max"],
                after_reveal=r["after_reveal"], teacher_score=r["teacher_score"],
                teacher_comment=r["teacher_comment"], flagged=r["flagged"], flag_note=r["flag_note"],
                flag_resolved=r["flag_resolved"], created=r["created"])
           for r in db().execute(sql, args)]
    return jsonify(attempts=out)


@app.post("/api/teacher/attempts/<int:tid>")
@teacher_required
def teacher_review(tid):
    d = request.get_json(silent=True) or {}
    row = db().execute("SELECT max FROM attempts WHERE id=?", (tid,)).fetchone() or abort(404)
    if "teacher_score" in d:
        ts = d["teacher_score"]
        ts = None if ts in (None, "") else max(0, min(row["max"], int(ts)))
        db().execute("UPDATE attempts SET teacher_score=? WHERE id=?", (ts, tid))
    if "teacher_comment" in d:
        db().execute("UPDATE attempts SET teacher_comment=? WHERE id=?", ((d["teacher_comment"] or "")[:2000], tid))
    if d.get("resolve_flag"):
        db().execute("UPDATE attempts SET flag_resolved=1 WHERE id=?", (tid,))
    db().commit()
    return jsonify(ok=True)


@app.get("/api/teacher/flags")
@teacher_required
def teacher_flags():
    a = [dict(kind="answer", id=r["id"], avatar=r["name"], qid=r["qid"], note=r["flag_note"],
              text=" / ".join((p.get("text") or "") for p in json.loads(r["answer"]).values()), created=r["created"])
         for r in db().execute("SELECT t.*, a.name FROM attempts t JOIN avatars a ON a.id=t.avatar_id "
                               "WHERE t.flagged=1 AND t.flag_resolved=0 ORDER BY t.id DESC")]
    c = [dict(kind="chat", id=r["id"], avatar=r["name"], qid=r["qid"], note=r["flag_note"], text=r["content"],
              created=r["created"])
         for r in db().execute("SELECT c.*, a.name FROM chats c JOIN avatars a ON a.id=c.avatar_id "
                               "WHERE c.flagged=1 AND c.flag_resolved=0 ORDER BY c.id DESC")]
    return jsonify(flags=sorted(a + c, key=lambda x: x["created"], reverse=True))


@app.post("/api/teacher/flags/<kind>/<int:fid>/resolve")
@teacher_required
def resolve_flag(kind, fid):
    table = {"answer": "attempts", "chat": "chats"}.get(kind) or abort(404)
    db().execute(f"UPDATE {table} SET flag_resolved=1 WHERE id=?", (fid,))
    db().commit()
    return jsonify(ok=True)


@app.get("/api/teacher/avatars")
@teacher_required
def teacher_avatars():
    return jsonify(avatars=[dict(r) for r in db().execute(
        "SELECT id, name, pin, disabled, created, last_seen FROM avatars ORDER BY name")])


@app.post("/api/teacher/avatars")
@teacher_required
def add_avatars():
    n = max(1, min(100, int((request.get_json(silent=True) or {}).get("count") or 1)))
    taken = [r[0] for r in db().execute("SELECT name FROM avatars")]
    new = generate(n, taken)
    db().executemany("INSERT INTO avatars (name, pin, created) VALUES (?,?,?)", [(a, p, now()) for a, p in new])
    db().commit()
    return teacher_avatars()


@app.post("/api/teacher/avatars/<int:aid>")
@teacher_required
def edit_avatar(aid):
    d = request.get_json(silent=True) or {}
    if "disabled" in d:
        db().execute("UPDATE avatars SET disabled=? WHERE id=?", (int(bool(d["disabled"])), aid))
    if d.get("new_pin"):
        db().execute("UPDATE avatars SET pin=? WHERE id=?", (f"{secrets.randbelow(10000):04d}", aid))
    db().commit()
    return teacher_avatars()


@app.get("/api/teacher/export.csv")
@teacher_required
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["avatar", "question", "section", "chapter", "type", "score", "max", "teacher_score",
                "after_model_answer", "submitted"])
    for r in db().execute("SELECT t.*, a.name FROM attempts t JOIN avatars a ON a.id=t.avatar_id ORDER BY t.id"):
        q = QUESTIONS.get(r["qid"], {})
        w.writerow([r["name"], r["qid"], q.get("section"), q.get("ch"),
                    "In-chapter" if q.get("kind") == "q" else "Exercise", r["score"], r["max"],
                    r["teacher_score"], "yes" if r["after_reveal"] else "", r["created"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=attempts.csv"})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=bool(os.environ.get("DEBUG")))
