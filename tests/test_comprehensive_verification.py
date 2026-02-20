"""Comprehensive verification test suite for TAPAN_AI system.

Tests all components, tools, reasoning layers, and end-to-end flows.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings
from src.core.reasoning_engine import ReasoningEngine
from src.core.perception_engine import PerceptionEngine
from src.core.emotional_engine import EmotionalEngine
from src.core.planning_engine import PlanningEngine
from src.llm.llm_dispatcher import LLMDispatcher
from src.memory.episodic_memory import EpisodicMemory
from src.memory.semantic_memory import SemanticMemory
from src.memory.persona_memory import PersonaMemory
from src.memory.memory_retriever import MemoryRetriever
from src.models import MemoryContext, PerceptionOutput, ReasoningOutput
from src.storage.sqlite_store import SQLiteStore
from src.storage.vector_store import create_vector_store
from src.storage.cognee_store import CogneeStore
from src.tools.finance_tool import FinanceTool
from src.tools.reminder_tool import ReminderTool
from src.tools.calendar_tool import CalendarTool
from src.tools.people_tool import PeopleTool
from src.tools.tool_registry import ToolRegistry
from src.core.orchestrator import Orchestrator
from src.core.output_sanitizer import OutputSanitizer
from src.core.reference_resolver import ReferenceResolver
from src.core.self_reflection import SelfReflectionEngine
from src.core.proactive_engine import ProactiveEngine
from src.core.performance_monitor import PerformanceMonitor
from src.llm.prompt_builder import PromptBuilder


class TestResults:
    """Track test results."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.results = {}
    
    def record(self, test_name: str, passed: bool, error: str = ""):
        """Record test result."""
        if passed:
            self.passed += 1
            print(f"[PASS] {test_name}")
        else:
            self.failed += 1
            print(f"[FAIL] {test_name}: {error}")
            self.errors.append(f"{test_name}: {error}")
        self.results[test_name] = {"passed": passed, "error": error}
    
    def summary(self):
        """Print summary."""
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY: {self.passed}/{total} passed, {self.failed} failed")
        print(f"{'='*60}")
        if self.errors:
            print("\nErrors:")
            for err in self.errors:
                print(f"  - {err}")


async def test_finance_tool_comprehensive(results: TestResults):
    """Test all finance tool operations."""
    print("\n" + "="*60)
    print("TESTING FINANCE TOOL - Comprehensive CRUD Operations")
    print("="*60)
    
    store = SQLiteStore(":memory:")
    await store.initialize()
    tool = FinanceTool(store)
    session_id = "test_session"
    
    # Mock reasoning and memory
    reasoning = ReasoningOutput(
        inferred_intent="financial_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=[],
        uncertainty=0.1,
        rationale="test",
    )
    memory = MemoryContext()
    
    # Test 1: Create Account
    try:
        result = await tool.execute(session_id, "create account savings with 10000", reasoning, memory)
        results.record("Finance: Create Account", result.success, result.output_text if not result.success else "")
        account_id = result.data.get("account_name") if result.success else None
    except Exception as e:
        results.record("Finance: Create Account", False, str(e))
    
    # Test 2: List Accounts
    try:
        result = await tool.execute(session_id, "list accounts", reasoning, memory)
        results.record("Finance: List Accounts", result.success and len(result.data.get("accounts", [])) > 0)
    except Exception as e:
        results.record("Finance: List Accounts", False, str(e))
    
    # Test 3: Get Account by Name
    try:
        result = await tool.execute(session_id, "get account savings", reasoning, memory)
        results.record("Finance: Get Account by Name", result.success)
    except Exception as e:
        results.record("Finance: Get Account by Name", False, str(e))
    
    # Test 4: Add Credit Transaction
    try:
        result = await tool.execute(session_id, "add 5000 to savings", reasoning, memory)
        results.record("Finance: Add Credit", result.success)
    except Exception as e:
        results.record("Finance: Add Credit", False, str(e))
    
    # Test 5: Add Debit Transaction
    try:
        result = await tool.execute(session_id, "spent 2000 from savings", reasoning, memory)
        results.record("Finance: Add Debit", result.success)
    except Exception as e:
        results.record("Finance: Add Debit", False, str(e))
    
    # Test 6: Show Balance
    try:
        result = await tool.execute(session_id, "show balance of savings", reasoning, memory)
        results.record("Finance: Show Balance", result.success)
    except Exception as e:
        results.record("Finance: Show Balance", False, str(e))
    
    # Test 7: Transfer
    try:
        await tool.execute(session_id, "create account wallet with 0", reasoning, memory)
        result = await tool.execute(session_id, "transfer 1000 from savings to wallet", reasoning, memory)
        results.record("Finance: Transfer", result.success)
    except Exception as e:
        results.record("Finance: Transfer", False, str(e))
    
    # Test 8: Transaction History
    try:
        result = await tool.execute(session_id, "show transaction history", reasoning, memory)
        results.record("Finance: Transaction History", result.success)
    except Exception as e:
        results.record("Finance: Transaction History", False, str(e))
    
    # Test 9: List Transactions by Account
    try:
        result = await tool.execute(session_id, "transactions for savings", reasoning, memory)
        results.record("Finance: Transactions by Account", result.success)
    except Exception as e:
        results.record("Finance: Transactions by Account", False, str(e))
    
    # Test 10: Monthly Summary
    try:
        result = await tool.execute(session_id, "monthly summary", reasoning, memory)
        results.record("Finance: Monthly Summary", result.success)
    except Exception as e:
        results.record("Finance: Monthly Summary", False, str(e))
    
    # Test 11: Category Summary
    try:
        result = await tool.execute(session_id, "category summary", reasoning, memory)
        results.record("Finance: Category Summary", result.success)
    except Exception as e:
        results.record("Finance: Category Summary", False, str(e))
    
    # Test 12: Update Account Balance
    try:
        result = await tool.execute(session_id, "set balance of savings to 15000", reasoning, memory)
        results.record("Finance: Update Balance", result.success)
    except Exception as e:
        results.record("Finance: Update Balance", False, str(e))
    
    # Test 13: Rename Account
    try:
        result = await tool.execute(session_id, "rename account savings to emergency_fund", reasoning, memory)
        results.record("Finance: Rename Account", result.success)
    except Exception as e:
        results.record("Finance: Rename Account", False, str(e))
    
    # Test 14: Update Transaction
    try:
        # First get a transaction ID
        hist_result = await tool.execute(session_id, "transaction history", reasoning, memory)
        if hist_result.success and hist_result.data.get("transactions"):
            tx_id = hist_result.data["transactions"][0].get("id")
            if tx_id:
                result = await tool.execute(session_id, f"update transaction {tx_id} note: updated note", reasoning, memory)
                results.record("Finance: Update Transaction", result.success)
            else:
                results.record("Finance: Update Transaction", False, "No transaction ID found")
        else:
            results.record("Finance: Update Transaction", False, "No transactions to update")
    except Exception as e:
        results.record("Finance: Update Transaction", False, str(e))
    
    # Test 15: Delete Account
    try:
        await tool.execute(session_id, "create account temp_account with 0", reasoning, memory)
        result = await tool.execute(session_id, "delete account temp_account", reasoning, memory)
        results.record("Finance: Delete Account", result.success)
    except Exception as e:
        results.record("Finance: Delete Account", False, str(e))


async def test_reasoning_intent_detection(results: TestResults):
    """Test reasoning and intent detection layer."""
    print("\n" + "="*60)
    print("TESTING REASONING & INTENT DETECTION LAYER")
    print("="*60)
    
    settings = Settings.from_env()
    settings.llm_provider = "mock"
    llm = LLMDispatcher(settings)
    reasoning_engine = ReasoningEngine(llm)
    emotional_engine = EmotionalEngine()
    perception_engine = PerceptionEngine(emotional_engine)
    
    test_cases = [
        ("add 500 to savings", "financial_update", ["finance_tool"]),
        ("remind me to call mom tomorrow", "reminder_management", ["reminder_tool"]),
        ("schedule meeting tomorrow at 5 pm", "calendar_management", ["calendar_tool"]),
        ("Ravi is my manager", "people_memory_update", ["people_tool"]),
        ("how much did I spend last month?", "financial_update", ["finance_tool"]),
        ("I feel stressed", "emotional_support", []),
        ("hello", "social_greeting", []),
    ]
    
    for user_text, expected_intent, expected_tools in test_cases:
        try:
            perception = await perception_engine.perceive(user_text)
            memory = MemoryContext()
            reasoning = await reasoning_engine.reason(user_text, perception, memory)
            
            intent_match = reasoning.inferred_intent == expected_intent or expected_intent in reasoning.inferred_intent
            tools_match = all(tool in reasoning.tool_candidates for tool in expected_tools) if expected_tools else True
            
            passed = intent_match and tools_match
            error = ""
            if not intent_match:
                error = f"Expected intent '{expected_intent}', got '{reasoning.inferred_intent}'"
            if not tools_match:
                error += f" Expected tools {expected_tools}, got {reasoning.tool_candidates}"
            
            results.record(f"Intent: '{user_text[:30]}'", passed, error)
        except Exception as e:
            results.record(f"Intent: '{user_text[:30]}'", False, str(e))


async def test_tool_registry(results: TestResults):
    """Test tool registry and tool connections."""
    print("\n" + "="*60)
    print("TESTING TOOL REGISTRY & TOOL CONNECTIONS")
    print("="*60)
    
    store = SQLiteStore(":memory:")
    await store.initialize()
    vector_store = create_vector_store(Settings.from_env())
    graph_store = CogneeStore(store)
    
    registry = ToolRegistry()
    registry.register(FinanceTool(store))
    registry.register(ReminderTool(store))
    registry.register(CalendarTool(store))
    registry.register(PeopleTool(store, graph_store))
    
    # Test 1: Tool Registration
    tool_names = registry.names()
    expected_tools = ["finance_tool", "reminder_tool", "calendar_tool", "people_tool"]
    all_registered = all(tool in tool_names for tool in expected_tools)
    results.record("Tool Registry: All Tools Registered", all_registered)
    
    # Test 2: Tool Retrieval
    for tool_name in expected_tools:
        tool = registry.get(tool_name)
        results.record(f"Tool Registry: Get {tool_name}", tool is not None)
    
    # Test 3: Tool Execution
    reasoning = ReasoningOutput(
        inferred_intent="financial_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=["finance_tool"],
        uncertainty=0.1,
        rationale="test",
    )
    memory = MemoryContext()
    
    try:
        result = await registry.execute(
            "finance_tool",
            "test_session",
            "create account test_account with 1000",
            reasoning,
            memory,
        )
        results.record("Tool Registry: Execute Finance Tool", result.success)
    except Exception as e:
        results.record("Tool Registry: Execute Finance Tool", False, str(e))


async def test_memory_system(results: TestResults):
    """Test memory system (episodic, semantic, persona)."""
    print("\n" + "="*60)
    print("TESTING MEMORY SYSTEM")
    print("="*60)
    
    store = SQLiteStore(":memory:")
    await store.initialize()
    vector_store = create_vector_store(Settings.from_env())
    graph_store = CogneeStore(store)
    
    episodic = EpisodicMemory(store)
    semantic = SemanticMemory(store, vector_store)
    persona = PersonaMemory(store)
    retriever = MemoryRetriever(episodic, semantic, persona, graph_store)
    
    # Test Episodic Memory
    try:
        from src.models import ConversationTurn
        turn = ConversationTurn(
            session_id="test",
            user_text="I prefer conservative investments",
            assistant_text="Noted",
            emotional_state="neutral",
        )
        await episodic.add_turn(turn)
        recent = await episodic.recent("test", limit=5)
        results.record("Memory: Episodic Add & Retrieve", len(recent) > 0)
    except Exception as e:
        results.record("Memory: Episodic Add & Retrieve", False, str(e))
    
    # Test Semantic Memory
    try:
        await semantic.upsert_fact("investment_preference", "conservative", confidence=0.9)
        await semantic.remember_text("User prefers conservative investments")
        retrieved = await semantic.retrieve("investment", limit=3)
        results.record("Memory: Semantic Store & Retrieve", len(retrieved) > 0)
    except Exception as e:
        results.record("Memory: Semantic Store & Retrieve", False, str(e))
    
    # Test Persona Memory
    try:
        profile = await persona.get_profile()
        await persona.learn_from_text("I am a software engineer")
        updated_profile = await persona.get_profile()
        results.record("Memory: Persona Profile", profile is not None and updated_profile is not None)
    except Exception as e:
        results.record("Memory: Persona Profile", False, str(e))
    
    # Test Memory Retriever
    try:
        context = await retriever.retrieve("test", "What retirement plan should I consider?", ["investment"])
        results.record("Memory: Retriever Integration", context is not None)
    except Exception as e:
        results.record("Memory: Retriever Integration", False, str(e))


async def test_end_to_end_pipeline(results: TestResults):
    """Test end-to-end pipeline."""
    print("\n" + "="*60)
    print("TESTING END-TO-END PIPELINE")
    print("="*60)
    
    try:
        from src.main import build_runtime
        
        settings = Settings.from_env()
        settings.llm_provider = "mock"
        settings.sqlite_path = ":memory:"
        
        runtime = await build_runtime(settings=settings)
        
        # Test various user inputs
        test_inputs = [
            "create account savings with 10000",
            "add 5000 to savings",
            "show accounts",
            "remind me to call mom tomorrow at 5 pm",
            "schedule meeting tomorrow at 10 am",
            "Ravi is my manager",
            "who is Ravi",
        ]
        
        for user_input in test_inputs:
            try:
                result = await runtime.orchestrator.handle_user_input("test_session", user_input)
                passed = result is not None and len(result.text) > 0
                results.record(f"E2E: '{user_input[:40]}'", passed)
            except Exception as e:
                results.record(f"E2E: '{user_input[:40]}'", False, str(e))
    except Exception as e:
        results.record("E2E: Pipeline Setup", False, str(e))


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TAPAN_AI COMPREHENSIVE VERIFICATION TEST SUITE")
    print("="*60)
    
    results = TestResults()
    
    # Run all test suites
    await test_finance_tool_comprehensive(results)
    await test_reasoning_intent_detection(results)
    await test_tool_registry(results)
    await test_memory_system(results)
    await test_end_to_end_pipeline(results)
    
    # Print summary
    results.summary()
    
    # Save results
    with open("tests/verification_results.json", "w") as f:
        json.dump(results.results, f, indent=2)
    
    print("\nResults saved to tests/verification_results.json")
    
    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
