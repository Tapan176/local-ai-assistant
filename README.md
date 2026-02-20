# TAPAN_AI v2

Production-ready, local-first cognitive AI companion with:

- Perception -> Memory -> Reasoning -> Planning -> Tooling -> Reflection pipeline
- Episodic, semantic, persona, and relationship memory
- Dynamic intent inference and uncertainty-aware clarification
- Async FastAPI + WebSocket + streaming + CLI interfaces
- Structured JSON logs and dependency-injected modular architecture

## Architecture

- `src/core/`: orchestrator, perception, reasoning, planning, emotion, reflection, proactive suggestions
- `src/memory/`: episodic/semantic/persona memory plus retrieval/saver services
- `src/storage/`: SQLite repository, vector backend (Chroma with fallback), graph store
- `src/tools/`: finance, reminder, people, calendar tool services
- `src/llm/`: provider dispatcher, BitNet/Ollama fallback chain, prompt builder, streaming
- `src/interfaces/`: CLI, API, WebSocket, voice interface with optional voice identity lock
- `src/config/`: runtime settings and system prompt

## Setup

Python 3.11+:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Optional env vars:

```bash
set TAPAN_LLM_PROVIDER=mock
set TAPAN_SQLITE_PATH=data/tapan_ai_v2.db
set TAPAN_CHROMA_PATH=data/chroma_v2
set TAPAN_API_HOST=127.0.0.1
set TAPAN_API_PORT=8000
set TAPAN_INTENT_CLASSIFIER=hybrid
set TAPAN_SEMANTIC_INTENT_MODEL=sentence-transformers/all-MiniLM-L6-v2
set TAPAN_SEMANTIC_INTENT_THRESHOLD=0.62
set TAPAN_SPACY_MODEL=en_core_web_sm
set TAPAN_BITNET_ENABLED=false
set TAPAN_BITNET_MODE=auto
set TAPAN_BITNET_CPP_EXECUTABLE=
set TAPAN_BITNET_CPP_MODEL_PATH=
```

Optional NLP upgrades (recommended for less hardcoded behavior):

```bash
.venv\Scripts\python -m pip install sentence-transformers spacy vaderSentiment
.venv\Scripts\python -m spacy download en_core_web_sm
```

With these installed:
- intent inference uses semantic embeddings (`sentence-transformers`) in hybrid mode
- entity extraction uses spaCy NER when available
- emotional scoring uses VADER sentiment when available

BitNet fallback:
- `TAPAN_BITNET_MODE=cpp` -> force local `bitnet.cpp` executable + GGUF model.
- `TAPAN_BITNET_MODE=service` -> force OpenAI-compatible BitNet HTTP service.
- `TAPAN_BITNET_MODE=auto` -> try local `bitnet.cpp` first, then service, then Ollama fallback chain.

## Run

CLI:

```bash
.venv\Scripts\python -c "from src.main import run_cli; run_cli()"
```

API:

```bash
.venv\Scripts\python -c "from src.main import run_api; run_api()"
```

You can also use `run_tapan.bat`.

Endpoints:

- `GET /health`
- `POST /chat`
- `ws://<host>:<port>/ws/{session_id}`
- `ws://<host>:<port>/ws-stream/{session_id}`

## Scenario Examples

- `bro kya hal chal`
- `add 400 to axis`
- `transfer 200 from axis to wallet`
- `remind me to call mom tomorrow 9 am`
- `schedule design review tomorrow at 5 pm`
- `Ravi is my manager` -> `who is Ravi`
- `I feel stressed and overwhelmed`

## Production Notes

- No static command registry in orchestration flow.
- Prompt leakage is sanitized before user output.
- All memory and tool state is local-first and persisted.
- Repository has been consolidated to deploy-focused modules only.
