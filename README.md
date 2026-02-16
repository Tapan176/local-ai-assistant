# TAPAN_AI – Personal AI Assistant (SQLite-First)

A modular, offline-first personal AI assistant built in Python.
Uses **SQLite** as the source of truth and optional **Cognee + Neo4j** for semantic/graph-based memory recall.

## Architecture

```
User Input → IntentParser (regex) → Orchestrator → Tool.execute()
                                         ↓
                                   MemoryRouter
                                    ↙        ↘
                              MemoryTool    CogneeTool
                              (SQLite)      (Cognee/Neo4j)
```

- **SQLite** = transactional truth (ACID, always available)
- **Cognee** = cognitive layer (graph traversal, semantic recall — optional)
- **MemoryRouter** picks the right backend per query

## Directory Structure

```
J/
├── src/
│   ├── agent/           # AI agent: orchestrator, intent parser, tools
│   │   ├── tools/       # BaseTool implementations (finance, memory, cognee, etc.)
│   │   ├── memory_router.py   # SQLite ↔ Cognee routing
│   │   ├── orchestrator.py    # Central event loop
│   │   └── intent_parser.py   # Deterministic regex routing
│   ├── core/            # Domain managers (finance, memory, habits, etc.)
│   ├── db/              # BaseRepository (universal SQLite CRUD)
│   ├── memory/          # Cognee brain, ingestion pipeline, recall guard
│   ├── service/         # Data service, scheduler, brain service
│   ├── cli/             # CLI app entry point
│   └── utils/           # Helpers
├── tests/               # Pytest test files
├── _schemas/            # SQL schema definitions
├── data/                # Runtime data (gitignored)
├── requirements.txt
└── .gitignore
```

## Setup

### Prerequisites
- **Python 3.10+**
- (Optional) **Neo4j** for graph memory
- (Optional) **Cognee** for vector memory

### Installation

```bash
# Clone & enter project
cd J

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root (gitignored):

```env
# Optional: Cognee/Neo4j config
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

## Run

```bash
# CLI mode
python -m src.cli.app

# Or via start script
python start.py
```

## Commands

| Category | Command | Example |
|----------|---------|---------|
| **Finance** | `expense <amt> <cat>` | `expense 500 food` |
| | `income <amt> <cat>` | `income 1000 salary` |
| | `transfer <amt> from A to B` | `transfer 500 from savings to wallet` |
| | `show accounts` / `balance` | |
| **Memory** | `remember <text>` | `remember I like pizza` |
| | `show memories` | |
| **Cognee** | `recall <query>` | `recall what I said about food` |
| | `deep recall <query>` | `deep recall gym habits` |
| | `search memory <query>` | `search memory pizza` |
| | `cognee health` | |
| **Experience** | `log <text>` | `log went to gym` |
| | `show experiences` / `stats` | |
| **Reminder** | `remind <text>` | `remind me to buy milk` |
| | `show reminders` | |
| **System** | `help` / `list` / `clear` / `exit` | |

**Hinglish supported:** `yaad rakho`, `dikhao`, `hata do`, etc.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_parser.py -v
pytest tests/test_memory_router.py -v
```

## Principles

- **SQLite Only**: Single source of truth — no JSON state files
- **No Hallucination**: Deterministic responses for data queries
- **Cognee Optional**: Graceful degradation when vector memory unavailable
- **Hinglish Default**: Natural Hindi-English interaction (70/30 rule)
- **OS Independent**: Works on Windows and Linux
- **Privacy First**: All data stays local in `data/`
