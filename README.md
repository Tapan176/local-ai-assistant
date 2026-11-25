# TAPAN_AI — a local-first, Jarvis-style personal assistant

Talk (or type) to it, and it **does things**: sets reminders that actually fire, keeps your tasks and notes,
searches the web, checks the weather, does exact maths, remembers who you are, briefs you each morning, and
(locally) reads/writes files in a sandbox and launches apps.

## How it works

```
 browser UI / CLI / API ──► AgentOrchestrator
                              │
                              ├─► Agent loop  ◄── LLM (OmniRoute → OpenRouter → Ollama), native tool calling
                              │     picks skills, runs them, reads results, repeats, answers
                              │
                              └─► Legacy pipeline (offline fallback when no LLM is reachable)
```

- **Agent loop** (`src/agent/`): the LLM chooses tools via OpenAI-style function calling. Models that reject
  `tools` automatically get a text-based tool protocol instead, so free/local models still work.
- **Skills** (`src/agent/skills/`) — see the table below.
- **Memory — three layers**
  1. *Facts*: things worth keeping (your preferences, people, goals) are saved with `remember` and injected into every chat.
  2. *Recent context*: the last 16 turns of the current conversation are replayed to the model.
  3. *Everything ever said*: every message is stored, and the `search_history` skill lets the assistant look up any
     past conversation by keyword or date ("what was the door code for the trip?"), even if it was never saved as a fact.
  All of it is stored in your database (SQLite locally, Postgres when hosted). Supermemory is an optional add-on.
- **Proactive**: a background scheduler fires due reminders into `/api/notifications`; the web UI shows, speaks
  and (with permission) pops them as desktop notifications even if you didn't ask.
- **Legacy pipeline** (`src/core/`): the original intent-classifier → tool pipeline. Still used offline
  (`TAPAN_LLM_PROVIDER=mock`) and as a fallback if the LLM providers are down.

| Skill | What it does |
|---|---|
| `get_current_time`, `calculate` | Real date/time (any timezone); safe exact arithmetic (no `eval`) |
| `remember` / `recall` / `forget` | Long-term memory about you |
| `add_note` / `search_notes` / `delete_note` | Notes |
| `add_task` / `list_tasks` / `complete_task` / `delete_task` | To-dos with priority and due date |
| `set_reminder` / `set_reminders` / `list_reminders` / `cancel_reminder` | Timed reminders that push notifications. `set_reminders` takes a whole pasted list at once (valid items are saved, bad ones are reported) |
| `daily_briefing` | Reminders + tasks + events + weather in one call |
| `web_search`, `fetch_url`, `get_weather` | Internet access (SSRF-guarded; Open-Meteo needs no key) |
| `finance_assistant`, `people_assistant`, `calendar_assistant` | Original tools, now callable by the agent |
| `list_files`, `read_file`, `write_file`, `open_url`, `open_app`, `system_info` | **Local only**: sandboxed to `TAPAN_WORKSPACE_DIR`; apps limited to an allow-list; never overwrites without `mode=overwrite` |

## The web UI

- **Responsive**: a full-height chat on phones (the side panel becomes a slide-over drawer), two columns on desktop.
  The composer follows the on-screen keyboard; installable to your home screen (PWA manifest).
- **Conversation history**: your chat is restored after a refresh and shared across devices (default thread `main`).
  The *History* tab lists past conversations to reopen or delete; *New* starts a fresh one. Saved facts persist across all of them.
- **Today panel**: weather, overdue / upcoming reminders, tasks and events at a glance; tick off tasks or cancel
  reminders in one tap. It refreshes itself after the assistant changes something.
- **Live feedback**: typing indicator, and chips showing what it is doing ("Setting reminders…", "Searching the web…").
- **Multiline input**: Enter sends, Shift+Enter adds a line (on touch screens Enter is a newline). Paste a list and it handles every item.
- **Voice**: mic button with live transcription. Spoken replies are *off / only after you used the mic / always*.
- Copy button on every message, timestamps and day separators, "jump to latest", `/` to focus the box, ↑ to recall your last message.

## Push notifications for reminders

Reminders reach your phone's lock screen **even when Tapan is closed** (Web Push, no app store, no third-party account).

- **Turn on**: in the *Today* panel tap *Turn on notifications*, or accept the offer that appears right after you set a
  reminder. The permission prompt only ever appears after a tap. *Send a test* confirms the whole path works.
- **Android / desktop Chrome, Edge, Firefox**: works in the browser tab or the installed app.
- **iPhone / iPad**: iOS only allows it for apps added to the Home Screen (Share → Add to Home Screen), iOS 16.4+.
- **Many at once**: more than three reminders firing together (say, after the server was asleep) arrive as one summary.
  A late reminder says when it was actually due.
- **Private**: each message is encrypted to your device; Google/Apple/Mozilla/Microsoft only relay ciphertext.
- **Safe by design**: subscription URLs are accepted only for the real push services (otherwise a signed-in client could make
  the server call arbitrary addresses); each reminder is claimed atomically so overlapping instances never notify twice.

**Important on free hosting:** a push can only be sent by a *running* server. If Render's free plan has put the service to
sleep, nothing fires until it wakes (the reminder then arrives late, marked "was due …"). For on-time delivery use an
always-on instance (`plan: starter`) or wake the server shortly before reminders are due.

## Recurring reminders, Snooze, Telegram

- **Recurring**: "remind me every weekday at 9 to take vitamins", "on the 1st of every month pay rent". Daily, weekdays, weekly
  (chosen days), monthly (month-end safe) and yearly, in your timezone and across daylight-saving changes. If the server was
  asleep it sends the latest missed one, not a pile. Cancelling stops the whole series.
- **Snooze from the notification**: the lock-screen notification has *Snooze 10 min* and *Snooze 1 h* buttons. They carry a signed,
  single-purpose token, so the service worker never holds your access token.
- **Telegram** (works on iPhone too): create a bot with @BotFather, paste its token in *Settings > Telegram*, tap the link to pair.
  Reminders arrive there with Snooze buttons, and you can chat with the assistant. Only the paired chat is answered.

## Design

- **Navigation**: on phones and tablets a bottom bar (Chat, Today, Money, Work, Growth, More) opens each section as a full-screen page;
  *More* holds History, Settings, appearance, install and lock. On desktop a left rail lists every section next to the chat and the
  side panel. The bar hides itself while the on-screen keyboard is up.
- **Appearance**: Auto (follows your device), Light or Dark, from the top bar on desktop or the *More* menu on a phone. The choice is
  remembered on that device and applied before the first paint, so there is no flash of the wrong colours.
- **Fast and private to load**: no web font and no 3D library are fetched from a CDN any more; everything the page draws is its own.
- Contrast, focus order and names are checked in both themes at phone, tablet and desktop sizes (axe in real Edge, no violations).

## Money: payments, EMIs, spending and subscriptions

The *Money* tab tracks what you have to pay, what you spend and what renews, and whether your banks can cover it.
Sections: Overview, Payments, Spending, Subscriptions, Banks.

- **Payments with EMIs**: enter a title, total, number of EMIs and the first EMI date; every later EMI falls on the same day of
  each month (day 31 becomes the last day of shorter months). Every EMI then has its **own amount and date** you can edit, add or
  remove, and **one common day** can be applied to all unpaid EMIs at once. If your edits stop the EMIs adding up to the total,
  it tells you by how much and offers to spread the rest evenly. **Spread equally keeps the EMIs whose amount you typed**
  (they show a *fixed* badge) and splits only what is left over the other unpaid EMIs; paid EMIs are never touched, and
  *Spread over all* replaces the fixed ones too. If you know the amount of each EMI, type that instead of the total and the
  total is worked out.
- **Three kinds of payment**: *EMIs*; *one payment with a due date* (for example a card's minimum due, with an optional
  outstanding total); and *no due date* (money you owe someone and will pay when you can: never overdue, never reminded, can be
  paid off in parts and then settled).
- **Groups**: give payments a group such as "Home loan". On the Overview, untick a group to leave it out of the totals (the
  choice is remembered on that device); bank shortfall warnings always count every payment.
- **Mark several EMIs paid** in one go, or tick them one after another quickly: every tick is saved, in order.
- **Mark paid / unpaid**: a tick box per EMI. Optionally the payment's bank balance is reduced when you tick it, and restored to
  the paisa when you untick.
- **Banks**: the accounts you pay from, with the balance you enter (it never connects to a real bank). Money warns when the EMIs
  due in the next 30 days exceed a bank's balance.
- **Advice**: plain rules always run (overdue first, shortfalls, your heaviest month, how many months of EMIs your balances cover).
  *Get AI advice* additionally asks your configured model for a short plan. It is sent payment names, amounts and bank names and
  balances, never notes, and the answer is labelled as not professional advice.
- **Reminders**: each upcoming EMI gets a normal reminder (9 am, by default the day before), so push and Telegram deliver it. The next
  12 EMIs of a payment have one; the window rolls forward as you pay.
- **From chat**: "add a phone EMI of 24000 over 6 months from 5 Dec", "mark my car loan EMI paid", "what EMIs are due?".
- **Spending**: a daily ledger (amount, category, note, date) with a month view: total, change on last month, per-day average,
  projected month-end, split by category, and an optional monthly budget. From chat: "spent 250 on lunch".
- **Subscriptions**: what renews and when, shown per month and per year. *Mark renewed* logs the charge as spending, can take
  it off the bank balance, and moves the date forward without day-of-month drift (31 Jan, 28 Feb, 31 Mar). Each one keeps a
  single reminder pointing at its next renewal; pausing removes it.
- **Export** every EMI and all spending as CSV. Money is stored as whole paise/cents, so a 36-EMI plan never drifts by a fraction.

Upgrading keeps your data: schema changes are additive only (new columns with defaults, new tables). The first time the new
version reads existing payments it also protects EMI amounts you had edited by hand, inferred from the data, without
changing any amount.

## Work

The *Work* tab is the same task list the chat and the Today panel use, with projects and a place for notes.

- **Tasks**: type one line and press Enter, or open the detailed form for a project, priority, due date and time, a reminder and
  details. A date without a time means *by the end of that day*, so a task due today is not overdue until the day is over. Open
  tasks are grouped Overdue, Today, This week, Later and No date; tick several quickly and every tick is saved.
- **Reminders follow the task**: at the due time, 9 am that morning, or 9 am the day before. Moving the date moves the reminder;
  finishing or deleting the task (here, in chat or on the Today panel) cancels it; clearing the date clears it.
- **Notes & plans**: meeting notes, plans and ideas with tags and pinning, searchable as you type.
- **From chat**: "add a task to the Atlas project: draft the spec by Friday, remind me that morning", "save a work note: …".

## Growth

The *Growth* tab keeps what you want to remember about living and working well.

- **Journal**: learnings, lessons, quotes and thoughts, with tags, search, pinning and a filter per kind.
- **Rulebook**: your own rules, numbered in the order you wrote them. The first line is the rule; the lines after are why it matters.
- **For today**: one rule, quote or lesson, the same all day and different tomorrow (pinned ones are preferred); *Another one*
  shows more without changing today's pick.
- **From chat**: "save this lesson: …", "add a rule: …", "what are my rules about money?", "a thought for today".

## Memory graph

Besides the flat list of things it remembers, the assistant keeps a small **graph** of the people, places, organisations and projects in
your life and how they connect ("Zorya works at Quillon Labs", "Quillon Labs is based in Lisbon", "Marek mentors me").

- **How it fills**: tell it a lasting fact and it stores the connection (`link_entities`, `describe_entity`); ask "what do you know about
  Zorya?" to read it back (`recall_connections`); "forget Zorya" removes a thing and its connections.
- **How it helps**: when you mention a stored name, the assistant is handed that thing's neighbourhood (two steps out) with your message,
  so "what should I tell Zorya about the Q4 numbers?" already knows where she works. No extra model call, and nothing is added when no
  stored name appears in your message. "Me" is a single node and is never expanded through, so one hub cannot drag in everything.
- **Settings → Memory graph**: search, and remove any thing or connection (two taps). Sizes are capped (5,000 things, 20,000 connections).
- **Safe by design**: stored text is flattened to one line and labelled as background data, never instructions.
- **Free, and no extra service**: two small tables in the same database (SQLite or Postgres/Supabase). The graph code is one module, so
  a Neo4j backend could replace it later without touching the assistant; for one person's life a hosted graph database adds a service
  to run and a size limit, and buys nothing at this scale.

## Pictures in chat

Tap the paperclip, paste a screenshot, or drop a picture on the chat (up to three at a time). The browser shrinks each one to at most
1280 px (JPEG, under about 1.2 MB) before sending, so a phone photo does not eat your data.

- **What happens**: a vision model describes the picture (receipts, bills, screenshots, documents, whiteboards, anything), and your
  assistant acts on that description: it can offer to log an expense from a receipt, add a payment plan from a bill, or save the key
  facts of a document as a work note or a memory.
- **What is kept**: the picture itself is **not stored** anywhere (not on the server, not in the database). Only a short description
  stays in the conversation, plus whatever you tell the assistant to save.
- **Safe by design**: text inside a picture is treated as data, never as instructions. The server re-checks the type (by the file's
  real bytes), size and count of every picture.
- **Cost**: roughly a fraction of a cent per picture on the default cheap vision model. `TAPAN_VISION_MODEL` changes the model;
  `TAPAN_VISION_DAILY_LIMIT` (default 60 picture requests per day, `0` = off) is a hard stop so it can never run away.

## Weather

Free providers with automatic fallback and no API keys: Open-Meteo, then MET Norway, then wttr.in (geocoding falls back to
OpenStreetMap Nominatim). Shared hosting IPs get rate-limited by Open-Meteo (HTTP 429); a rate-limited provider is skipped for
10 minutes instead of being retried. Requests carry a generic software User-Agent only, never your name or repository.

## Quick start (Windows)

```powershell
uv venv .venv --python 3.12          # or: python -m venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
copy .env.example .env               # then edit: provider, key, your name, city, timezone
.\run_tapan.bat                      # opens http://127.0.0.1:8000
```

The message box is multiline (Enter sends, Shift+Enter adds a line), so you can paste a whole list — *"set these reminders: 1. call mom tomorrow 9am 2. tax form Friday 5pm …"* — and every item is created in one go.

Try: *"remind me to stretch in 10 minutes"*, *"what's the weather"*, *"search the web for the latest Python release"*,
*"add a task: file taxes, high priority, due Friday"*, *"good morning"*, *"remember I prefer meetings after 11"*.

Optional heavier extras (semantic routing for the offline pipeline, local voice, Supermemory):
`pip install -r requirements-extras.txt`.

## LLM setup with OmniRoute

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) is a self-hosted OpenAI-compatible gateway that routes
across many providers (including free tiers) with automatic fallback.

1. Run OmniRoute (default `http://localhost:20128`) and create an API key under *Dashboard → Endpoints*.
2. In `.env`: `TAPAN_LLM_PROVIDER=omniroute`, `OMNIROUTE_API_KEY=...`, `TAPAN_OMNIROUTE_MODEL=auto`.
3. Optionally add `OPENROUTER_API_KEY` / a local Ollama as automatic fallbacks.

Not every routed model supports tool calling well — if answers feel dumb or tools are ignored, pick a stronger
model/combo via `TAPAN_OMNIROUTE_MODEL`. Failing providers are skipped for 60 s so one outage doesn't slow every message.

## API

| Endpoint | Notes |
|---|---|
| `GET /health` | Public liveness (used by Render) |
| `POST /chat` | `{session_id, message}` |
| `WS /ws/{session}` | First frame `{"auth": "<token>"}`; then plain-text messages. Replies plus live `tool_start` / `tool_end` events |
| `WS /ws-stream/{session}` | Same auth; chunked reply |
| `GET /api/notifications?after=<id>` | Fired reminders |
| `GET /api/briefing`, `GET /api/skills` | Daily briefing data (overdue / today / upcoming reminders, tasks, events, weather); installed skills |
| `GET /api/history?session_id=&limit=` | A conversation's recent messages (restored by the UI after a refresh) |
| `GET /api/conversations`, `DELETE /api/conversations/{id}` | Past conversations (titled by their first message); delete a transcript (saved facts are kept) |
| `POST /api/tasks/{id}/complete`, `DELETE /api/reminders/{id}` | Quick actions used by the *Today* panel |
| `GET /api/push/key`, `POST /api/push/subscribe`, `POST /api/push/unsubscribe`, `POST /api/push/test` | Web Push: VAPID public key, register / remove this device, send a test (rate-limited) |

When `TAPAN_API_TOKEN` is set, everything except `/health` and the static UI needs
`Authorization: Bearer <token>` (or `X-API-Key`). WebSockets authenticate with the first frame `{"auth": "<token>"}` or the same header on the handshake — never the URL, because URLs end up in access logs.
**`TAPAN_ENV` other than `local` refuses to start without a token.** Chat is rate-limited per client.

## Hosting: Render + Supabase

Render runs the server; Supabase Postgres stores everything (the Render free plan has no disk). Nothing in the
app is Supabase-specific: any Postgres URI in `TAPAN_DATABASE_URL` works, and leaving it blank uses local SQLite.

1. **Database** — create a Supabase project, then *Connect → Session pooler* and copy the URI (set/reset the
   database password under *Project Settings → Database*). Tables are created automatically on first start
   (row-level security is enabled on all of them, so Supabase's public API keys cannot read your data).
2. **Server** — Render → *New → Blueprint* → this repo and branch. Paste `TAPAN_DATABASE_URL` and
   `OPENROUTER_API_KEY` when prompted; copy the generated `TAPAN_API_TOKEN` afterwards. The UI asks for it once.
3. Open the service URL, enter the token, talk to it.

Free-plan caveats: the service sleeps after about 15 minutes without traffic, and a sleeping server cannot deliver
reminders. Keep it awake for free with a Supabase scheduled job that calls `/health` every 10 minutes (pg_cron + pg_net):

```sql
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;
select cron.schedule('keep-assistant-awake', '*/10 * * * *',
  $$ select net.http_get(url := 'https://YOUR-SERVICE.onrender.com/health', timeout_milliseconds := 20000); $$);
-- undo: select cron.unschedule('keep-assistant-awake');
```

### Why saves can feel slow, and what is done about it

A request that touches the database costs a network round trip per statement, and a free Render server and a free Supabase
database are rarely in the same place (about 60 ms between Singapore and Mumbai). The app therefore sends each multi-statement
write as one message (atomic, values bound by psycopg), reads independent data in parallel, and re-syncs reminders in one
transaction instead of one query per EMI. Measured at 60 ms a hop, saving a 24-EMI payment went from 4.4 s to 0.7 s, "spread
equally" from 4.4 s to 0.5 s and marking five EMIs paid from 5.4 s to 0.3 s. `TAPAN_PG_BATCH=0` switches back to one statement
per hop. Pick a Render region next to your database. Every request also shows a loading pill ("Saving…", "Loading…") that counts the
seconds and says when the server is slow.

One always-on free web service uses about 730 of Render's 750 free instance hours a month, so this only works if it is your
only free service. For a guaranteed always-on server switch `plan: free` to `starter` in `render.yaml`.
Supabase free projects also pause after a week with no activity. Local skills (files, apps) are automatically
disabled when hosted, and the legacy SQLite-introspection verifier is disabled in Postgres mode.

## Development

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements.txt -r requirements-extras.txt
$env:TAPAN_LLM_PROVIDER="mock"; .venv\Scripts\python.exe -m pytest
```

Add a skill: write `async def handler(ctx, args) -> str | dict` and `registry.add(name, description, schema, handler)`
in `src/agent/skills/`. The LLM sees it immediately; no routing code to touch.
