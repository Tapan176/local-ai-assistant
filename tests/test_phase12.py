"""
PHASE 12 - Persona & Self-Model Tests (60 tests)
=================================================
Tests for:
1. Persona traits (10 tests)
2. Personal values (10 tests)
3. Emotional state (10 tests)
4. Decision profile (10 tests)
5. Relation context (10 tests)
6. Decision Engine (10 tests)

Run: python tests/test_phase12.py
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.orchestrator import Orchestrator
from src.agent.tools.persona_tool_v2 import PersonaToolV2
from src.agent.tools.relation_tool import RelationTool
from src.agent.decision_engine import DecisionEngine


class Phase12TestRunner:
    """Run 60 Phase 12 tests"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.agent = Orchestrator(data_dir)
        self.persona = PersonaToolV2(data_dir)
        self.relations = RelationTool(data_dir)
        self.decision = DecisionEngine(data_dir)
        self.passed = 0
        self.failed = 0
        self.results = []
    
    def _check(self, test_id: str, condition: bool, desc: str, output: str = ""):
        """Record test result"""
        status = "[PASS]" if condition else "[FAIL]"
        if condition:
            self.passed += 1
        else:
            self.failed += 1
        self.results.append({"id": test_id, "status": status, "desc": desc})
        out_preview = (output[:50] + "...") if len(output) > 50 else output
        print(f"  {status} {test_id}: {desc} {out_preview}")
    
    # ============================================================
    # 1. PERSONA TRAITS (10 tests)
    # ============================================================
    def test_persona_traits(self):
        print("\n=== PERSONA TRAITS (10 tests) ===")
        
        # PT01: Set a trait
        r = self.persona.execute("set_trait", {"key": "creativity", "value": "high", "category": "personality"})
        self._check("PT01", r.success, "Set trait", r.message)
        
        # PT02: Get trait back
        r = self.persona.execute("get_trait", {"key": "creativity"})
        self._check("PT02", "high" in r.message.lower(), "Get trait", r.message)
        
        # PT03: Set identity trait
        r = self.persona.execute("set_trait", {"key": "name", "value": "Tapan", "category": "identity"})
        self._check("PT03", r.success, "Set identity", r.message)
        
        # PT04: List traits by category
        r = self.persona.execute("list_traits", {"category": "personality"})
        self._check("PT04", "creativity" in r.message.lower(), "List by category", r.message)
        
        # PT05: List all traits
        r = self.persona.execute("list_traits", {})
        self._check("PT05", "IDENTITY" in r.message.upper() or "identity" in r.message, "List all", r.message)
        
        # PT06: Update existing trait
        r = self.persona.execute("set_trait", {"key": "creativity", "value": "very high"})
        self._check("PT06", r.success, "Update trait", r.message)
        
        # PT07: Verify update
        r = self.persona.execute("get_trait", {"key": "creativity"})
        self._check("PT07", "very high" in r.message.lower(), "Verify update", r.message)
        
        # PT08: Get non-existent trait
        r = self.persona.execute("get_trait", {"key": "nonexistent123"})
        self._check("PT08", "no trait" in r.message.lower() or "not found" in r.message.lower(), "Get missing", r.message)
        
        # PT09: Set inferred trait
        r = self.persona.execute("set_trait", {"key": "morning_person", "value": "yes", "source": "inferred"})
        self._check("PT09", r.success, "Inferred trait", r.message)
        
        # PT10: Verify in DB
        conn = sqlite3.connect(self.data_dir / "persona.db")
        row = conn.execute("SELECT * FROM traits WHERE key = 'creativity'").fetchone()
        conn.close()
        self._check("PT10", row is not None, "DB verification")
    
    # ============================================================
    # 2. PERSONAL VALUES (10 tests)
    # ============================================================
    def test_personal_values(self):
        print("\n=== PERSONAL VALUES (10 tests) ===")
        
        # PV01: Add value (or exists is ok)
        r = self.persona.execute("add_value", {"value": "honesty", "importance": 9, "reason": "trust foundation"})
        self._check("PV01", r.success or "exists" in r.message.lower(), "Add value", r.message)
        
        # PV02: Add another (or exists is ok)
        r = self.persona.execute("add_value", {"value": "family", "importance": 10, "reason": "everything"})
        self._check("PV02", r.success or "exists" in r.message.lower(), "Add family", r.message)
        
        # PV03: List values
        r = self.persona.execute("list_values", {})
        self._check("PV03", "honesty" in r.message.lower() or "family" in r.message.lower(), "List values", r.message)
        
        # PV04: Values list contains high priority ones
        r = self.persona.execute("list_values", {})
        self._check("PV04", "family" in r.message.lower() and "honesty" in r.message.lower(), "Has key values")
        
        # PV05: Duplicate value rejected
        r = self.persona.execute("add_value", {"value": "honesty", "importance": 5})
        self._check("PV05", not r.success or "exist" in r.message.lower(), "Duplicate reject", r.message)
        
        # PV06: Update value importance
        r = self.persona.execute("update_value", {"value": "honesty", "importance": 10})
        self._check("PV06", r.success or "updated" in r.message.lower(), "Update importance", r.message)
        
        # PV07: Add value with low importance (or exists is ok)
        r = self.persona.execute("add_value", {"value": "adventure", "importance": 3})
        self._check("PV07", r.success or "exists" in r.message.lower(), "Add low priority", r.message)
        
        # PV08: Get core values via accessor
        values = self.persona.get_core_values()
        self._check("PV08", isinstance(values, list), f"Get core values: {values}")
        
        # PV09: Via agent
        r = self.agent.process("my values")
        self._check("PV09", "value" in r.lower() or "honesty" in r.lower() or "family" in r.lower(), "Agent values", r)
        
        # PV10: Verify in DB
        conn = sqlite3.connect(self.data_dir / "persona.db")
        count = conn.execute("SELECT COUNT(*) FROM personal_values").fetchone()[0]
        conn.close()
        self._check("PV10", count >= 2, f"DB has {count} values")
    
    # ============================================================
    # 3. EMOTIONAL STATE (10 tests)
    # ============================================================
    def test_emotional_state(self):
        print("\n=== EMOTIONAL STATE (10 tests) ===")
        
        # ES01: Log mood
        r = self.persona.execute("log_mood", {"mood": "happy", "mood_score": 8, "energy_level": 7, "stress_level": 2})
        self._check("ES01", r.success and "happy" in r.message.lower(), "Log happy", r.message)
        
        # ES02: Get current mood
        r = self.persona.execute("get_current_mood", {})
        self._check("ES02", "happy" in r.message.lower() or "mood" in r.message.lower(), "Get mood", r.message)
        
        # ES03: Log stressed mood
        r = self.persona.execute("log_mood", {"mood": "stressed", "mood_score": 4, "stress_level": 8, "trigger": "work deadline"})
        self._check("ES03", r.success, "Log stressed", r.message)
        
        # ES04: Get emotional state dict
        state = self.persona.get_current_emotional_state()
        self._check("ES04", state.get("mood") == "stressed", f"State dict: {state}")
        
        # ES05: Mood history
        r = self.persona.execute("mood_history", {"days": 7})
        self._check("ES05", "Mood History" in r.message or "No mood" in r.message, "Mood history", r.message)
        
        # ES06: Via agent "I'm feeling X"
        r = self.agent.process("I am feeling excited")
        self._check("ES06", "mood" in r.lower() or "excited" in r.lower() or "logged" in r.lower(), "Agent mood", r)
        
        # ES07: Via agent "my current mood"
        r = self.agent.process("my current mood")
        self._check("ES07", "mood" in r.lower() or "excited" in r.lower() or "stressed" in r.lower(), "Agent get mood", r)
        
        # ES08: Log with notes
        r = self.persona.execute("log_mood", {"mood": "anxious", "notes": "upcoming presentation"})
        self._check("ES08", r.success, "Log with notes", r.message)
        
        # ES09: Verify in DB
        conn = sqlite3.connect(self.data_dir / "persona.db")
        count = conn.execute("SELECT COUNT(*) FROM emotional_state").fetchone()[0]
        conn.close()
        self._check("ES09", count >= 3, f"DB has {count} mood logs")
        
        # ES10: Score bar visualization
        r = self.persona.execute("get_current_mood", {})
        self._check("ES10", "[" in r.message and "]" in r.message, "Score bar shown", r.message)
    
    # ============================================================
    # 4. DECISION PROFILE (10 tests)
    # ============================================================
    def test_decision_profile(self):
        print("\n=== DECISION PROFILE (10 tests) ===")
        
        # DP01: Get full profile
        r = self.persona.execute("get_decision_profile", {})
        self._check("DP01", "risk_tolerance" in r.message.lower(), "Get profile", r.message)
        
        # DP02: Update dimension
        r = self.persona.execute("update_decision_dimension", {"dimension": "risk_tolerance", "score": 0.7})
        self._check("DP02", r.success, "Update risk", r.message)
        
        # DP03: Verify update
        profile = self.persona.get_decision_profile_dict()
        self._check("DP03", abs(profile.get("risk_tolerance", 0) - 0.7) < 0.01, f"Risk is {profile.get('risk_tolerance')}")
        
        # DP04: Update frugal dimension
        r = self.persona.execute("update_decision_dimension", {"dimension": "frugal_vs_spender", "score": 0.2})
        self._check("DP04", r.success, "Update frugal", r.message)
        
        # DP05: Via agent
        r = self.agent.process("my decision style")
        self._check("DP05", "profile" in r.lower() or "risk" in r.lower() or "decision" in r.lower(), "Agent profile", r)
        
        # DP06: Score clamping (> 1.0)
        r = self.persona.execute("update_decision_dimension", {"dimension": "data_vs_gut", "score": 1.5})
        profile = self.persona.get_decision_profile_dict()
        self._check("DP06", profile.get("data_vs_gut", 0) <= 1.0, f"Clamped to {profile.get('data_vs_gut')}")
        
        # DP07: Score clamping (< 0.0)
        r = self.persona.execute("update_decision_dimension", {"dimension": "data_vs_gut", "score": -0.5})
        profile = self.persona.get_decision_profile_dict()
        self._check("DP07", profile.get("data_vs_gut", 0) >= 0.0, f"Clamped to {profile.get('data_vs_gut')}")
        
        # DP08: Unknown dimension
        r = self.persona.execute("update_decision_dimension", {"dimension": "unknown_xyz", "score": 0.5})
        self._check("DP08", not r.success or "unknown" in r.message.lower(), "Unknown rejected", r.message)
        
        # DP09: Profile has all dimensions
        profile = self.persona.get_decision_profile_dict()
        expected = ["risk_tolerance", "impulsive_vs_deliberate", "data_vs_gut", "frugal_vs_spender"]
        self._check("DP09", all(d in profile for d in expected), f"Has all dims: {len(profile)}")
        
        # DP10: Verify in DB
        conn = sqlite3.connect(self.data_dir / "persona.db")
        count = conn.execute("SELECT COUNT(*) FROM decision_profile").fetchone()[0]
        conn.close()
        self._check("DP10", count >= 7, f"DB has {count} dimensions")
    
    # ============================================================
    # 5. RELATION CONTEXT (10 tests)
    # ============================================================
    def test_relation_context(self):
        print("\n=== RELATION CONTEXT (10 tests) ===")
        
        # RC01: Add person with context
        r = self.relations.execute("add", {"name": "Maya", "relationship": "friend", "trust_level": 8})
        self._check("RC01", r.success or "exists" in r.message.lower(), "Add Maya", r.message)
        
        # RC02: Set context for person
        r = self.relations.execute("set_context", {"name": "Maya", "talk_style": "casual", "communication_preference": "text"})
        self._check("RC02", r.success or "updated" in r.message.lower(), "Set context", r.message)
        
        # RC03: Get context back
        r = self.relations.execute("get_context", {"name": "Maya"})
        self._check("RC03", "maya" in r.message.lower() or "casual" in r.message.lower(), "Get context", r.message)
        
        # RC04: Set topics to avoid
        r = self.relations.execute("set_context", {"name": "Maya", "topics_to_avoid": ["politics", "ex"]})
        self._check("RC04", r.success, "Set avoid topics", r.message)
        
        # RC05: Add shared memory
        r = self.relations.execute("add_memory", {"name": "Maya", "memory": "Met at college canteen 2015"})
        self._check("RC05", r.success, "Add memory", r.message)
        
        # RC06: Get shared memories
        r = self.relations.execute("get_memories", {"name": "Maya"})
        self._check("RC06", "college" in r.message.lower() or "memories" in r.message.lower(), "Get memories", r.message)
        
        # RC07: Add another person
        r = self.relations.execute("add", {"name": "BossRaj", "relationship": "boss"})
        self._check("RC07", r.success or "exists" in r.message.lower(), "Add BossRaj", r.message)
        
        # RC08: Set formal context for boss
        r = self.relations.execute("set_context", {"name": "BossRaj", "talk_style": "formal", "communication_preference": "email"})
        self._check("RC08", r.success or "updated" in r.message.lower(), "Boss context", r.message)
        
        # RC09: Via agent
        r = self.agent.process("context for Maya")
        self._check("RC09", "maya" in r.lower() or "context" in r.lower() or "friend" in r.lower(), "Agent context", r)
        
        # RC10: Verify in DB
        conn = sqlite3.connect(self.data_dir / "relations.db")
        row = conn.execute("SELECT talk_style FROM relations WHERE LOWER(name) = 'maya'").fetchone()
        conn.close()
        self._check("RC10", row is not None and row[0] == "casual", f"DB talk_style: {row}")
    
    # ============================================================
    # 6. DECISION ENGINE (10 tests)
    # ============================================================
    def test_decision_engine(self):
        print("\n=== DECISION ENGINE (10 tests) ===")
        
        # DE01: Get financial context
        ctx = self.decision.get_financial_context()
        self._check("DE01", isinstance(ctx, dict), f"Financial ctx: {list(ctx.keys())[:3]}")
        
        # DE02: Get habit context
        ctx = self.decision.get_habit_context()
        self._check("DE02", isinstance(ctx, dict), f"Habit ctx: {list(ctx.keys())[:3]}")
        
        # DE03: Get emotional context
        ctx = self.decision.get_emotional_context()
        self._check("DE03", "mood" in ctx, f"Emotional ctx: {ctx.get('mood')}")
        
        # DE04: Get persona context
        ctx = self.decision.get_persona_context()
        self._check("DE04", "risk_tolerance" in ctx or "decision_profile" in ctx, f"Persona ctx present")
        
        # DE05: Get relation context
        ctx = self.decision.get_relation_context("Maya")
        self._check("DE05", ctx.get("available") or ctx.get("name"), f"Relation ctx: {ctx.get('name')}")
        
        # DE06: Full context gathering
        ctx = self.decision.gather_full_context("should I buy a laptop?")
        self._check("DE06", "financial" in ctx and "emotional" in ctx, f"Full ctx has {len(ctx)} keys")
        
        # DE07: Warnings generated
        ctx = self.decision.gather_full_context("should I quit my job?")
        self._check("DE07", "warnings" in ctx, f"Warnings: {ctx.get('warnings', [])[:2]}")
        
        # DE08: Recommendations generated
        ctx = self.decision.gather_full_context("should I buy crypto?")
        self._check("DE08", "recommendations" in ctx, f"Recs: {ctx.get('recommendations', [])[:2]}")
        
        # DE09: Advice context prompt
        prompt = self.decision.get_advice_context_prompt("should I invest in stocks?")
        self._check("DE09", "DECISION CONTEXT" in prompt, f"Prompt has {len(prompt)} chars")
        
        # DE10: Should approve purchase
        result = self.decision.should_approve_purchase(500)
        self._check("DE10", "approve" in result and "reason" in result, f"Approve: {result}")
    
    def run_all(self):
        """Run all 60 tests"""
        print("=" * 60)
        print("  PHASE 12 - PERSONA & SELF-MODEL TESTS (60)")
        print("=" * 60)
        print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  Data Dir: {self.data_dir}")
        print("=" * 60)
        
        self.test_persona_traits()      # 10
        self.test_personal_values()     # 10
        self.test_emotional_state()     # 10
        self.test_decision_profile()    # 10
        self.test_relation_context()    # 10
        self.test_decision_engine()     # 10
        
        print("\n" + "=" * 60)
        print(f"  RESULTS: {self.passed} passed, {self.failed} failed")
        print(f"  PASS RATE: {100*self.passed/(self.passed+self.failed):.1f}%")
        print("=" * 60)
        
        return self.passed, self.failed


if __name__ == "__main__":
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    runner = Phase12TestRunner(data_dir)
    passed, failed = runner.run_all()
    
    exit(0 if failed == 0 else 1)
