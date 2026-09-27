# H446 Revision Coach

A revision web app for OCR A Level Computer Science (H446) students, built on the 405 questions from
the PG Online textbook (236 in-chapter questions and 169 end-of-chapter exercises, 12 sections).

**Students** sign in with an anonymous avatar and PIN, and then:
- answer any question, with the textbook's code, tables and diagrams; trace tables are filled in cell by cell, and diagrams can be described or uploaded as a photo;
- get AI marking against the OCR mark-scheme standard, with feedback on each part, the key terms a full-mark answer needs, and misconceptions;
- improve and resubmit as often as they like; model answers unlock on request after the first attempt;
- ask a tutor for hints before answering (it won't give the answer away) or for explanations afterwards;
- generate fresh exam-style practice questions on the same skill, which the AI also marks;
- see their progress by section and chapter, a "focus next" list and a study streak, and get an AI study plan for the week.

**The teacher** gets a dashboard with:
- a class heatmap (avatar × section) and the weakest chapters across the class;
- every answer with its AI feedback; you can override any mark and leave a comment the student sees;
- safeguarding flags, raised when an answer or chat message suggests a student may be at risk;
- avatar management (add, disable, new PIN, printable sign-in cards), usage and cost, and a CSV export.

No student names are stored anywhere in the app. Keep your own list of who has which avatar.

## Files

| Path | What it is |
|---|---|
| `server.py` | Flask app: API, sign-in, database (SQLite) |
| `ai.py` | All Claude calls: marking, tutor, practice questions, study plans |
| `static/` | The web app (plain HTML/CSS/JS, no build step) |
| `export_content.py` | Builds `content/` from the textbook transcriptions and PDF |
| `avatars.py` | Generates avatar names and PINs |
| `content/` | Questions and diagrams (**not in git** - textbook copyright) |
| `avatars.csv` | The avatar list the app starts with (**not in git** - contains PINs) |

## Setup

You need an Anthropic API key from https://console.anthropic.com (a school/organisation account),
and somewhere to run a small Python web app.

Settings (environment variables):

| Variable | Required | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | the school's API key |
| `TEACHER_PASSWORD` | yes | password for the teacher dashboard |
| `DATA_DIR` | no | where the database and uploaded photos live (default `./instance`) |
| `MODEL` | no | Claude model, default `claude-opus-5` |
| `DAILY_LIMIT` | no | AI requests per student per day, default 60 |
| `SECRET_KEY` | no | cookie signing key; generated and saved in `DATA_DIR` if not set |

### Run it on any computer (quickest test)

    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...  TEACHER_PASSWORD=choose-one
    python server.py            # then open http://localhost:8000

Set `MOCK_AI=1` to try the whole app without an API key (canned marking and replies).

### Host it for the class

Any host that runs a Docker container with a persistent disk works, for example Render, Railway, Fly.io,
Google Cloud Run (with a mounted volume), or a school server:

    docker build -t h446-coach .
    docker run -d -p 8000:8000 -v h446-data:/data \
      -e ANTHROPIC_API_KEY=sk-ant-... -e TEACHER_PASSWORD=choose-one h446-coach

The `/data` volume holds the database. Back it up; if it is lost, students' progress is lost.
Serve it over HTTPS (all the hosts above do this for you).

On first start the app loads `avatars.csv` (60 avatars). Hand out the cards from
**Dashboard → Avatars → Print sign-in cards**, and add more there when needed.

### Rebuilding the question content

    AL_PDF="/path/to/A Level Computer Science Digital Text Book.pdf" python export_content.py

## Cost

Each marking, tutor reply, practice question or study plan is one AI request. A marking request with
`claude-opus-5` is roughly 3-6k input tokens and 1-3k output tokens, so about $0.04-$0.10. A tutor reply
costs less. As a guide, 30 students each marking about 10 answers a week comes to roughly $15-$30 a week.
The dashboard shows the actual running total. To lower costs, set `MODEL=claude-sonnet-5` (about 60% cheaper)
or reduce `DAILY_LIMIT`.

## Safeguarding and data

- Students are anonymous avatars. Answers and chat are stored against the avatar only.
- The app tells students not to include personal details. Answer text and photos are sent to
  Anthropic's API for marking.
- Claude is told to treat student text as work to assess, never as instructions, to stay on computer science,
  and to flag possible risk to a student for the teacher. Flags appear under **Dashboard → Flags**.
  They are a backstop, not a replacement for the school's safeguarding process.
- AI marks are guidance, not final grades. The teacher can override any mark.
- Check with your data protection lead before going live, and check Anthropic's current terms for
  services used by under-18s when you set up the API account.
