"""
Reasoning Engine - Multi-step reasoning with personal alignment
Provides structured thinking for complex questions with finance/habit awareness
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import sqlite3


@dataclass
class ReasoningStep:
    """A single step in the reasoning trace"""
    step_num: int
    description: str
    result: str
    confidence: float = 0.8


@dataclass
class ProsCons:
    """Pros and cons analysis"""
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    
    def add_pro(self, item: str):
        self.pros.append(item)
    
    def add_con(self, item: str):
        self.cons.append(item)
    
    def get_balance(self) -> str:
        """Get overall sentiment"""
        if len(self.pros) > len(self.cons):
            return "positive"
        elif len(self.cons) > len(self.pros):
            return "negative"
        return "neutral"


@dataclass
class SafetyCheck:
    """Safety check result"""
    check_type: str
    passed: bool
    warning: str = ""
    severity: str = "info"  # info, warning, danger


@dataclass
class ReasoningTrace:
    """Complete reasoning trace for a query"""
    query: str
    steps: List[ReasoningStep] = field(default_factory=list)
    pros_cons: Optional[ProsCons] = None
    safety_checks: List[SafetyCheck] = field(default_factory=list)
    decision: str = ""
    confidence: float = 0.7
    reasoning_type: str = "general"  # general, finance, planning, habit
    
    def add_step(self, description: str, result: str, confidence: float = 0.8):
        step = ReasoningStep(
            step_num=len(self.steps) + 1,
            description=description,
            result=result,
            confidence=confidence
        )
        self.steps.append(step)
    
    def has_warnings(self) -> bool:
        return any(not sc.passed for sc in self.safety_checks)
    
    def get_summary(self) -> str:
        """Get reasoning summary"""
        summary = f"Reasoning ({len(self.steps)} steps):\n"
        for step in self.steps:
            summary += f"  {step.step_num}. {step.description}: {step.result}\n"
        return summary


class ReasoningEngine:
    """Multi-step reasoning engine with personal alignment"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        
        # Keywords for detecting query types
        self.finance_keywords = [
            'buy', 'purchase', 'spend', 'afford', 'cost', 'price', 'loan',
            'emi', 'investment', 'save', 'budget', 'expense', 'kharcha',
            'paisa', 'rupees', 'rs', 'phone', 'laptop', 'bike', 'car'
        ]
        
        self.planning_keywords = [
            'plan', 'today', 'tomorrow', 'schedule', 'routine', 'day',
            'week', 'morning', 'evening', 'time', 'manage'
        ]
        
        self.habit_keywords = [
            'habit', 'exercise', 'gym', 'workout', 'meditation', 'read',
            'streak', 'routine', 'daily', 'consistency'
        ]
    
    def detect_query_type(self, query: str) -> str:
        """Detect the type of query"""
        query_lower = query.lower()
        
        # Check for finance queries
        if any(kw in query_lower for kw in self.finance_keywords):
            return "finance"
        
        # Check for planning queries
        if any(kw in query_lower for kw in self.planning_keywords):
            return "planning"
        
        # Check for habit queries
        if any(kw in query_lower for kw in self.habit_keywords):
            return "habit"
        
        return "general"
    
    def reason(self, query: str, context: Dict = None) -> ReasoningTrace:
        """
        Perform multi-step reasoning on a query
        
        Args:
            query: User's question
            context: Dict with finance_state, habits, profile, memories
        
        Returns:
            ReasoningTrace with steps, pros/cons, safety checks
        """
        context = context or {}
        query_type = self.detect_query_type(query)
        
        trace = ReasoningTrace(
            query=query,
            reasoning_type=query_type
        )
        
        # Step 1: Understand the query
        trace.add_step(
            "Understanding query",
            f"Query type: {query_type}",
            0.9
        )
        
        # Route to specific reasoning
        if query_type == "finance":
            self._finance_reasoning(trace, query, context)
        elif query_type == "planning":
            self._planning_reasoning(trace, query, context)
        elif query_type == "habit":
            self._habit_reasoning(trace, query, context)
        else:
            self._general_reasoning(trace, query, context)
        
        return trace
    
    def _finance_reasoning(self, trace: ReasoningTrace, query: str, context: Dict):
        """Finance-aware reasoning with safety checks"""
        finance_state = context.get('finance_state', {})
        profile = context.get('profile', {})
        
        balance = finance_state.get('balance', 0)
        monthly_income = finance_state.get('monthly_income', 0)
        monthly_expense = finance_state.get('monthly_expense', 0)
        risk_level = profile.get('risk_level', 'moderate')
        
        # Step 2: Analyze financial context
        trace.add_step(
            "Checking financial state",
            f"Balance: ₹{balance:,.0f}, Monthly spend: ₹{monthly_expense:,.0f}",
            0.95
        )
        
        # Extract amount from query if present
        amount = self._extract_amount(query)
        
        if amount:
            # Step 3: Affordability check
            affordability_ratio = (amount / balance * 100) if balance > 0 else float('inf')
            
            trace.add_step(
                "Affordability analysis",
                f"Item cost: ₹{amount:,.0f} ({affordability_ratio:.0f}% of balance)",
                0.9
            )
            
            # Pros/Cons
            pros_cons = ProsCons()
            
            if affordability_ratio < 30:
                pros_cons.add_pro("Well within budget")
                trace.safety_checks.append(SafetyCheck(
                    check_type="affordability",
                    passed=True,
                    warning="",
                    severity="info"
                ))
            elif affordability_ratio < 50:
                pros_cons.add_pro("Affordable but significant")
                pros_cons.add_con("Uses half of savings")
                trace.safety_checks.append(SafetyCheck(
                    check_type="affordability",
                    passed=True,
                    warning="Moderate impact on savings",
                    severity="warning"
                ))
            else:
                pros_cons.add_con(f"Uses {affordability_ratio:.0f}% of balance")
                pros_cons.add_con("May affect financial security")
                trace.safety_checks.append(SafetyCheck(
                    check_type="affordability",
                    passed=False,
                    warning=f"⚠️ High cost: {affordability_ratio:.0f}% of your balance!",
                    severity="danger"
                ))
            
            # EMI check
            if 'emi' in query.lower() or 'loan' in query.lower():
                emi_monthly = amount / 12  # Simple 12-month estimate
                emi_ratio = (emi_monthly / monthly_income * 100) if monthly_income > 0 else 50
                
                trace.add_step(
                    "EMI impact analysis",
                    f"Est. EMI: ₹{emi_monthly:,.0f}/month ({emi_ratio:.0f}% of income)",
                    0.8
                )
                
                if emi_ratio > 30:
                    pros_cons.add_con(f"EMI would be {emi_ratio:.0f}% of income")
                    trace.safety_checks.append(SafetyCheck(
                        check_type="emi",
                        passed=False,
                        warning="EMI burden may be too high",
                        severity="danger"
                    ))
            
            # Risk level consideration
            if risk_level == 'conservative':
                if affordability_ratio > 20:
                    pros_cons.add_con("Not aligned with conservative spending style")
            elif risk_level == 'aggressive':
                pros_cons.add_pro("You're comfortable with higher spending")
            
            trace.pros_cons = pros_cons
            
            # Decision
            balance_score = pros_cons.get_balance()
            if balance_score == "positive":
                trace.decision = "appears_affordable"
                trace.confidence = 0.8
            elif balance_score == "negative":
                trace.decision = "reconsider"
                trace.confidence = 0.7
            else:
                trace.decision = "neutral"
                trace.confidence = 0.6
        else:
            # General finance question
            trace.add_step(
                "General finance query",
                "No specific amount detected",
                0.7
            )
            trace.decision = "provide_info"
    
    def _planning_reasoning(self, trace: ReasoningTrace, query: str, context: Dict):
        """Planning-aware reasoning using reminders, habits, routines"""
        reminders = context.get('reminders', [])
        habits = context.get('habits', [])
        profile = context.get('profile', {})
        
        routine = profile.get('daily_routine', 'balanced')
        
        # Step 2: Gather commitments
        pending_count = len(reminders)
        habits_count = len(habits)
        
        trace.add_step(
            "Gathering commitments",
            f"Reminders: {pending_count}, Habits: {habits_count}",
            0.9
        )
        
        # Step 3: Check routine preference
        trace.add_step(
            "Checking routine style",
            f"Preferred style: {routine}",
            0.85
        )
        
        # Pros/Cons for busy day
        pros_cons = ProsCons()
        
        if pending_count > 5:
            pros_cons.add_con("Many pending tasks")
        else:
            pros_cons.add_pro("Manageable task load")
        
        if habits_count > 0:
            streaks = [h.get('streak', 0) for h in habits if isinstance(h, dict)]
            if streaks and max(streaks) > 5:
                pros_cons.add_pro(f"Good habit streaks (max: {max(streaks)})")
        
        trace.pros_cons = pros_cons
        trace.decision = "plan_generated"
        trace.confidence = 0.8
    
    def _habit_reasoning(self, trace: ReasoningTrace, query: str, context: Dict):
        """Habit-aware reasoning"""
        habits = context.get('habits', [])
        profile = context.get('profile', {})
        
        # Step 2: Analyze habits
        active_habits = len(habits)
        
        trace.add_step(
            "Analyzing habits",
            f"Active habits: {active_habits}",
            0.9
        )
        
        if habits:
            # Find best streak
            streaks = []
            for h in habits:
                if isinstance(h, dict):
                    streaks.append((h.get('name', 'Unknown'), h.get('streak', 0)))
            
            if streaks:
                best = max(streaks, key=lambda x: x[1])
                trace.add_step(
                    "Best performing habit",
                    f"{best[0]}: {best[1]} day streak",
                    0.85
                )
        
        trace.decision = "habit_advice"
        trace.confidence = 0.75
    
    def _general_reasoning(self, trace: ReasoningTrace, query: str, context: Dict):
        """General reasoning for non-specific queries"""
        memories = context.get('memories', [])
        
        # Step 2: Search context
        trace.add_step(
            "Searching knowledge base",
            f"Found {len(memories)} relevant memories",
            0.7
        )
        
        trace.decision = "general_response"
        trace.confidence = 0.6
    
    def _extract_amount(self, query: str) -> Optional[float]:
        """Extract monetary amount from query"""
        import re
        
        query_lower = query.lower()
        
        # Match patterns in order of specificity
        patterns = [
            (r'(\d+)\s*(?:lakh|lac)\b', 100000),  # 5 lakh
            (r'(\d+)\s*(?:hazar|thousand)\b', 1000),  # 50 hazar
            (r'(\d+)k\b', 1000),  # 50k
            (r'(?:rs\.?|₹|rupees)\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', 1),  # Rs. 50,000
            (r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?)', 1),  # 50,000 with commas
            (r'\b(\d{3,})\b', 1),  # Plain numbers like 60000 (at least 3 digits)
        ]
        
        for pattern, multiplier in patterns:
            match = re.search(pattern, query_lower)
            if match:
                num_str = match.group(1).replace(',', '')
                try:
                    amount = float(num_str) * multiplier
                    return amount
                except ValueError:
                    continue
        
        return None
    
    def get_finance_state(self) -> Dict:
        """Get current finance state from database"""
        finance_db = self.data_dir / "finance.db"
        
        if not finance_db.exists():
            return {'balance': 0, 'monthly_income': 0, 'monthly_expense': 0}
        
        conn = sqlite3.connect(finance_db)
        cursor = conn.cursor()
        
        # Get total balance
        cursor.execute("SELECT COALESCE(SUM(balance), 0) FROM accounts")
        balance = cursor.fetchone()[0]
        
        # Get this month's transactions
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
            FROM transactions
            WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')
        """)
        row = cursor.fetchone()
        monthly_income = row[0] if row else 0
        monthly_expense = row[1] if row else 0
        
        conn.close()
        
        return {
            'balance': balance,
            'monthly_income': monthly_income,
            'monthly_expense': monthly_expense
        }
    
    def get_habits_state(self) -> List[Dict]:
        """Get current habits with calculated streaks from logs"""
        habits_db = self.data_dir / "habits.db"
        
        if not habits_db.exists():
            return []
        
        conn = sqlite3.connect(habits_db)
        cursor = conn.cursor()
        
        # Get all habits from the table (schema lacks streak/active columns)
        cursor.execute("""
            SELECT id, name, description, frequency, created_at
            FROM habits
        """)
        
        habits = []
        for row in cursor.fetchall():
            habit_id = row[0]
            # Calculate streak from habit_logs
            cursor.execute("""
                SELECT COUNT(*) FROM habit_logs
                WHERE habit_id = ? AND log_date >= date('now', '-7 days')
            """, (habit_id,))
            recent_count = cursor.fetchone()[0]
            
            habits.append({
                'name': row[1],
                'description': row[2] or '',
                'frequency': row[3],
                'streak': recent_count,  # Use recent completions as proxy
                'created_at': row[4]
            })
        
        conn.close()
        return habits
    
    def get_pending_reminders(self) -> List[Dict]:
        """Get pending reminders"""
        reminders_db = self.data_dir / "reminders.db"
        
        if not reminders_db.exists():
            return []
        
        conn = sqlite3.connect(reminders_db)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, text, remind_at
            FROM reminders
            WHERE status = 'pending'
            ORDER BY remind_at ASC
            LIMIT 10
        """)
        
        reminders = []
        for row in cursor.fetchall():
            reminders.append({
                'id': row[0],
                'text': row[1],
                'remind_at': row[2]
            })
        
        conn.close()
        return reminders
    
    def build_full_context(self, profile: Dict = None) -> Dict:
        """Build complete context for reasoning"""
        return {
            'finance_state': self.get_finance_state(),
            'habits': self.get_habits_state(),
            'reminders': self.get_pending_reminders(),
            'profile': profile or {},
            'memories': []
        }


def get_reasoning_engine(data_dir: Path = None) -> ReasoningEngine:
    """Factory function for reasoning engine"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data"
    return ReasoningEngine(data_dir)
