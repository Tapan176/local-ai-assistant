"""Interactive CLI for TAPAN_AI v2."""

from __future__ import annotations

from src.config.settings import Settings
from src.core.orchestrator import Orchestrator
from src.llm.streaming import stream_text


async def run_cli(orchestrator: Orchestrator, settings: Settings) -> None:
    print("TAPAN_AI v2 CLI")
    print("Type 'exit' to stop.\n")
    session_id = "cli-session"

    while True:
        user_text = input("You: ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            print("Bye.")
            break

        response = await orchestrator.handle_user_input(session_id=session_id, user_text=user_text)
        print("TAPAN_AI: ", end="", flush=True)
        async for chunk in stream_text(response.text, chunk_size=settings.stream_chunk_size, delay_seconds=0.0):
            print(chunk, end="", flush=True)
        print()

