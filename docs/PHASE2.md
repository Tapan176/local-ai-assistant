# Phase 2 plan: from a helpful assistant to a J.A.R.V.I.S.-style one

Phase 1 (done) built the foundation: chat with tools, reminders with push and Telegram, money (EMIs, spending, subscriptions),
work and growth notebooks, pictures, graph memory, daily briefing, optional wake word, data export.

What makes a "Jarvis" feel different is not one feature. It is five qualities: it **speaks up first** (proactive), it **knows the
whole picture** (connected data), it **does things** (acts, not only answers), it is **always there** (voice, background, every device)
and it **earns trust** (private, predictable, reversible). The plan below is grouped by those qualities and ordered by value for one
person on free hosting.

Constraints that shape every choice: one user, free tiers (Render free sleeps, Supabase free has a size limit), public repository
(no personal data in code or tests), privacy first, and every outward action must be reversible or confirmed.

## A. Proactive: it tells you before you ask (highest value, lowest cost)

| Feature | What it does | Notes |
|---|---|---|
| Smart nudges | "Your card bill is due in 2 days and your bank account is short by X", "You have not logged spending for 3 days" | Rules first (no AI call), reuses the daily-briefing machinery |
| Weekly review | Sunday message: spending vs budget, tasks done, EMIs paid, one learning from the journal | Same engine as the daily briefing |
| Evening wrap-up | "3 tasks still open, tomorrow has 2 EMIs" | Optional, off by default |
| Anomaly alerts | A subscription price went up, a spend is 3x the usual for that category | Needs 2-3 months of data |
| Smart snooze | Learns that you snooze "call" reminders to the evening and offers that time | Small, noticeable |

## B. Connected: one picture of your life

| Feature | What it does | Notes |
|---|---|---|
| Google Calendar (read, then write) | Today's meetings in the briefing, reminders that respect your calendar, "move my 3 pm" | OAuth in a public repo means tokens live only in the database, scopes minimal |
| Email triage (read only first) | Bills and due dates found in Gmail become payment suggestions; "anything from my bank today?" | Read-only, summarised, nothing stored but the extracted facts |
| Documents search | Upload PDFs (policies, loan agreements, warranties); ask "when does my insurance renew?" | Vector search already exists as a store interface; chunk and embed on upload |
| Receipts to ledger | A photographed receipt becomes a spending entry in one tap (the picture reading exists; add the confirm step) | Quick win on top of phase 1 |
| Bank SMS / statement import | Paste or upload a statement, spending categorised automatically | No bank API logins, ever; file import only |
| Graph memory v2 | Auto-suggest connections the assistant noticed ("Is Zorya the same as Zorya Shah?"), merge duplicates, a visual map | Needs a review screen so nothing is merged silently |

## C. Acts: it does things, safely

| Feature | What it does | Notes |
|---|---|---|
| Routines and rules | "When I say good night: set tomorrow's alarm reminder and read the weather", "Every 1st: remind me to review subscriptions" | A small rule engine (trigger, conditions, actions) over the existing tools |
| Multi-step tasks | "Plan my week": reads tasks, calendar, EMIs, proposes a plan, you approve, it creates the reminders | Plan, show, approve, then act; never act first |
| Draft and send (with approval) | Drafts a message or email; you tap send | Approval step is mandatory for anything outward |
| Smart home / devices | Home Assistant or a webhook: lights, AC, "leaving home" scene | Only if you own such devices; MCP or webhooks |
| MCP tool plug-ins | Add tools (notes apps, maps, shopping lists) without code changes | The agent already uses a tool registry |
| Undo | Every write the assistant makes is logged with a one-tap undo for 24 hours | Trust feature; also protects your payment data |

## D. Always there: voice and every device

| Feature | What it does | Notes |
|---|---|---|
| **Native Android app (the real wake word)** | Always-on "Hey Tapan" in the background, lock-screen widget, share-sheet ("share a picture or link to Tapan"), home-screen quick actions | A web page cannot listen in the background. Options: a thin Kotlin/Flutter shell around the same API with an on-device wake-word engine (Porcupine free tier or openWakeWord), or Capacitor wrapping the web app plus a native wake-word plugin |
| Natural voice conversation | Streaming speech both ways, interruptible, short answers when spoken | Browser speech now; later an on-device or free neural TTS; keep spoken replies much shorter than written ones |
| Offline basics | Reminders and the day view work without network, sync when back | Service worker already caches the shell; add a local queue for writes |
| Wear OS / watch | Reminder actions (done, snooze) on the wrist | After the native app exists |
| Telegram as a full client | Pictures, voice notes, daily briefing, approvals via buttons | Mostly built; add voice-note transcription |

## E. Trust: private, predictable, reversible

- Spend caps per day for any paid model call, with a visible meter in Settings (pictures already have one).
- Encrypted backups to a place you choose (Drive or local file), plus a **restore** path (export exists; import does not).
- Prompt-injection guard for web pages and emails the assistant reads (data is already labelled as data; add a quarantine for tool results that ask for actions).
- A "what do you know about me" screen: memories, graph and settings in one place with delete buttons.
- Login hardening: optional passkey instead of a pasted token; per-device sessions you can revoke.
- Health dashboard: scheduler heartbeat, push delivery rate, last backup, model failures (some exists under Status).

## Suggested order

1. **Phase 2.0 (small, high value):** smart nudges and weekly review, receipt-to-ledger confirm step, data **import/restore**, undo log, LLM spend meter.
2. **Phase 2.1 (connect):** Google Calendar read, documents search, graph v2 with review screen.
3. **Phase 2.2 (act):** routines and rules, multi-step plans with approval, MCP plug-ins.
4. **Phase 2.3 (always there):** native Android shell with on-device wake word and share target; then voice conversation polish.
5. **Later:** email triage, smart home, watch.

## Decisions I need from you before starting

1. Do you want the **native Android app**? It is the only way to get a true always-on wake word and a share target. It costs real effort (separate codebase, Play Store or sideloaded APK, background-battery rules) so I would do it after 2.0 to 2.2.
2. Which accounts may the assistant connect to (Google Calendar, Gmail, Drive)? Each one is a privacy decision; I would start read-only.
3. Do you own smart-home devices (Home Assistant, smart plugs, TV)? If not, section C stays software-only.
4. Monthly money you are willing to spend on model calls (the current setup uses free or near-free models). Better voice and vision cost a little.
5. Anything you want from Jarvis that is not listed (for example: workouts and health logging, travel planning, shopping lists, learning plans, a "second brain" for reading).
