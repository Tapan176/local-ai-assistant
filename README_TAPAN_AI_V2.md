# TAPAN_AI v2

Enterprise-grade, local-first, memory-driven AI companion with a cognitive architecture:

- Perception -> Memory Retrieval -> Reasoning -> Planning -> Tool Execution -> Response Generation -> Self Reflection
- Episodic, semantic, and persona memory
- Dynamic intent inference (no command dictionary / no static command router)
- FastAPI + WebSocket + CLI interfaces
- Async-first orchestration and repository-style storage

## Architecture

The implementation is in `tapan_ai/` with the exact modular layout:

- `tapan_ai/core/`: orchestration, perception, reasoning, planning, emotional intelligence, self-reflection
- `tapan_ai/memory/`: episodic, semantic, persona memory + retrieval/saver services
- `tapan_ai/storage/`: SQLite repository, vector store (Chroma preferred, in-memory fallback), graph relationships
- `tapan_ai/tools/`: finance, reminder, people, calendar tools + registry
- `tapan_ai/llm/`: dispatcher, prompt builder, streaming utilities
- `tapan_ai/interfaces/`: CLI, REST/WebSocket API, voice scaffold
- `tapan_ai/config/`: env settings + system prompt
- `tapan_ai/main.py`: dependency injection and app composition root

## Cognitive Pipeline

Every input is processed by:

1. `PerceptionEngine`: tone, ambiguity, entities, emotional state
2. `MemoryRetriever`: episodic + semantic + persona + relationship graph retrieval
3. `ReasoningEngine`: intent inference + uncertainty + candidate actions/tools
4. `PlanningEngine`: choose `respond` / `clarify` / `tool`
5. Tool execution when needed (`finance_tool`, `reminder_tool`, `people_tool`, `calendar_tool`)
6. Prompt construction and contextual response generation
7. `SelfReflectionEngine`: coherence scoring, contradiction risk, storage policy
8. `MemorySaver`: stores turn + semantic/persona updates + consolidation

## Setup (Python 3.11+)

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Optional environment variables:

```bash
set TAPAN_LLM_PROVIDER=mock
set TAPAN_SQLITE_PATH=data/tapan_ai_v2.db
set TAPAN_CHROMA_PATH=data/chroma_v2
set TAPAN_LOG_LEVEL=INFO
```

Provider options:

- `mock` (default): fully local fallback
- `ollama`: set `TAPAN_OLLAMA_URL` and `TAPAN_OLLAMA_MODEL`
- `openai`: set `OPENAI_API_KEY`

## Run

CLI:

```bash
python -m tapan_ai.main
```

API:

```bash
python -c "from tapan_ai.main import run_api; run_api()"
```

- REST chat endpoint: `POST /chat`
- WebSocket endpoint: `ws://127.0.0.1:8000/ws/{session_id}`

## Testing Examples

Run focused v2 tests:

```bash
pytest -q tests/test_tapan_ai_v2_pipeline.py -p no:cacheprovider
```

Manual scenario prompts:

- Casual chat: `bro kya hal chal`
- Financial update: `add 400 to axis`
- Emotional support: `I am feeling stressed and overwhelmed`
- Ambiguous command: `do it`
- Continuity: `my name is Arjun` -> `what is my name`
- Topic switch: finance -> reminder -> emotional chat in one session

## Prompt Leakage Protection

- `config/system_prompt.yaml` is used only as hidden system context.
- Response generation explicitly instructs the model to never expose system rules.
- Tool and conversational responses are normalized to user-facing language.
- Self-reflection detects low-coherence responses and adapts persona memory.

