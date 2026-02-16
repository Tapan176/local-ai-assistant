"""
PHASE 13: Decision Engine V2 - Financial Conscience Brain

Strict saver mode (70/30):
- DEFAULT = SAY NO
- Only approve if post-spend buffer is safe
- EMI < 30% income
- Category whitelist: health, learning, family, rare experiences

Features:
1. Full decision pipeline (all context sources)
2. Risk level assessment
3. Alternatives + delay plans
4. Ride mode (1 sentence max)
"""
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from enum import Enum
import sqlite3
import json
import re


class RiskLevel(Enum):
  LOW = "low"
  MEDIUM = "medium"
  HIGH = "high"
  CRITICAL = "critical"


class DecisionDomain(Enum):
  FINANCE = "finance"
  TRAVEL = "travel"
  FOOD = "food"
  CAREER = "career"
  HEALTH = "health"
  RELATIONSHIP = "relationship"
  LEARNING = "learning"
  GENERAL = "general"


@dataclass
class DecisionResult:
  """Structured decision output"""
  approved: bool
  recommendation: str
  risk_level: RiskLevel
  reasoning: str
  numbers: Dict[str, float]
  tradeoffs: List[str]
  alternatives: List[str]
  action_steps: List[str]
  delay_plan: Optional[str]
  ride_mode_response: str


class DecisionEngineV2:
  """
  Financial Conscience Brain - Strict Saver Mode

  DEFAULT = SAY NO
  Approval only when:
  1. Post-spend balance > (30-day bills + 20% buffer)
  2. EMI < 30% monthly income
  3. Category is whitelisted (health, learning, family, rare)
  """

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.rules = self._load_rules()
    self.monthly_income = self._get_monthly_income()

  def _load_rules(self) -> Dict:
    """Load persona rules from JSON"""
    rules_path = self.data_dir / "persona_rules.json"
    if rules_path.exists():
      return json.loads(rules_path.read_text())
    return {
      "financial_conscience": {
        "mode": "strict_saver",
        "save_ratio": 0.7,
        "spend_ratio": 0.3
      }
    }

  def _conn(self, db_name: str):
    """Get DB connection"""
    path = self.data_dir / db_name
    if not path.exists():
      return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

  def _get_monthly_income(self) -> float:
    """Get monthly income from history or default"""
    conn = self._conn("finance.db")
    if not conn:
      return self.rules.get("income_tracking", {}).get("default_monthly", 50000)

    try:
      cursor = conn.cursor()
      # Get average monthly income from last 3 months
      cursor.execute("""
        SELECT AVG(monthly_total) as avg_income FROM (
          SELECT strftime('%Y-%m', date) as month, SUM(amount) as monthly_total
          FROM transactions WHERE type = 'income'
          GROUP BY month ORDER BY month DESC LIMIT 3
        )
      """)
      row = cursor.fetchone()
      if row and row['avg_income']:
        return row['avg_income']
    except:
      pass
    finally:
      conn.close()

    return self.rules.get("income_tracking", {}).get("default_monthly", 50000)

  # =====================================
  # CONTEXT GATHERING
  # =====================================

  def get_financial_state(self) -> Dict[str, Any]:
    """Get comprehensive financial state"""
    conn = self._conn("finance.db")
    if not conn:
      return {"available": False}

    try:
      cursor = conn.cursor()

      # Total balance
      cursor.execute("SELECT COALESCE(SUM(balance), 0) as total FROM accounts")
      balance = cursor.fetchone()['total']

      # 30-day spending
      cursor.execute("""
        SELECT COALESCE(SUM(ABS(amount)), 0) as spent
        FROM transactions WHERE type = 'expense' 
        AND date >= DATE('now', '-30 days')
      """)
      monthly_spend = cursor.fetchone()['spent']

      # Daily average
      daily_avg = monthly_spend / 30 if monthly_spend else 0

      # Top categories
      cursor.execute("""
        SELECT category, SUM(ABS(amount)) as total
        FROM transactions WHERE type = 'expense' 
        AND date >= DATE('now', '-30 days')
        GROUP BY category ORDER BY total DESC LIMIT 5
      """)
      top_cats = [{"category": r['category'], "amount": r['total']} for r in cursor.fetchall()]

      return {
        "available": True,
        "balance": balance,
        "monthly_spend": monthly_spend,
        "daily_avg": daily_avg,
        "monthly_income": self.monthly_income,
        "save_rate": (self.monthly_income - monthly_spend) / self.monthly_income if self.monthly_income else 0,
        "top_categories": top_cats
      }
    finally:
      conn.close()

  def get_upcoming_obligations(self, days: int = 30) -> Dict[str, Any]:
    """Get upcoming bills and fixed expenses"""
    conn = self._conn("reminders.db")
    bills = []
    total = 0

    if conn:
      try:
        cursor = conn.cursor()
        future = (date.today() + timedelta(days=days)).isoformat()

        cursor.execute("""
          SELECT text, remind_date FROM reminders
          WHERE remind_date <= ? AND remind_date >= DATE('now')
          AND status = 'active'
          AND (LOWER(text) LIKE '%bill%' OR LOWER(text) LIKE '%pay%'
             OR LOWER(text) LIKE '%emi%' OR LOWER(text) LIKE '%rent%'
             OR LOWER(text) LIKE '%fee%' OR LOWER(text) LIKE '%loan%')
        """, (future,))

        for r in cursor.fetchall():
          amount = self._extract_amount(r['text'])
          bills.append({"text": r['text'], "date": r['remind_date'], "amount": amount or 0})
          total += amount or 0
      except:
        pass
      finally:
        conn.close()

    return {"bills": bills, "total": total, "count": len(bills)}

  def get_habit_state(self) -> Dict[str, Any]:
    """Get habit streaks and status"""
    conn = self._conn("habits.db")
    if not conn:
      return {"available": False}

    try:
      cursor = conn.cursor()
      today = date.today().isoformat()

      cursor.execute("""
        SELECT h.name, h.frequency, h.streak,
             (SELECT MAX(done_date) FROM habit_logs WHERE habit_id = h.id) as last_done
        FROM habits h WHERE h.status = 'active'
      """)

      habits = []
      streaks_at_risk = []
      total_streak = 0

      for r in cursor.fetchall():
        streak = r['streak'] or 0
        total_streak += streak
        habit = {
          "name": r['name'],
          "streak": streak,
          "last_done": r['last_done'],
          "done_today": r['last_done'] == today
        }
        habits.append(habit)

        if r['frequency'] == 'daily' and r['last_done'] != today:
          streaks_at_risk.append(r['name'])

      return {
        "available": True,
        "habits": habits,
        "count": len(habits),
        "total_streak": total_streak,
        "streaks_at_risk": streaks_at_risk,
        "done_today": sum(1 for h in habits if h['done_today'])
      }
    except:
      return {"available": False}
    finally:
      conn.close()

  def get_emotional_state(self) -> Dict[str, Any]:
    """Get current mood and energy"""
    conn = self._conn("persona.db")
    if not conn:
      return {"mood": "neutral", "energy": 5, "stress": 3}

    try:
      cursor = conn.cursor()
      cursor.execute("""
        SELECT mood, mood_score, energy_level, stress_level
        FROM emotional_state ORDER BY log_date DESC, log_time DESC LIMIT 1
      """)
      row = cursor.fetchone()

      if row:
        return {
          "mood": row['mood'],
          "mood_score": row['mood_score'],
          "energy": row['energy_level'],
          "stress": row['stress_level'],
          "is_stressed": row['stress_level'] >= 7,
          "is_low_energy": row['energy_level'] <= 3
        }
      return {"mood": "neutral", "energy": 5, "stress": 3}
    except:
      return {"mood": "neutral", "energy": 5, "stress": 3}
    finally:
      conn.close()

  def get_past_outcomes(self, domain: str = None, limit: int = 5) -> List[Dict]:
    """Get past decision outcomes for learning"""
    conn = self._conn("persona.db")
    if not conn:
      return []

    try:
      cursor = conn.cursor()
      if domain:
        cursor.execute("""
          SELECT domain, situation, decision_made, outcome, lesson_learned
          FROM decision_log WHERE LOWER(domain) = LOWER(?)
          ORDER BY decision_date DESC LIMIT ?
        """, (domain, limit))
      else:
        cursor.execute("""
          SELECT domain, situation, decision_made, outcome, lesson_learned
          FROM decision_log ORDER BY decision_date DESC LIMIT ?
        """, (limit,))

      return [dict(r) for r in cursor.fetchall()]
    except:
      return []
    finally:
      conn.close()

  def get_pending_reminders(self, days: int = 7) -> List[Dict]:
    """Get pending reminders for next N days"""
    conn = self._conn("reminders.db")
    if not conn:
      return []

    try:
      cursor = conn.cursor()
      future = (date.today() + timedelta(days=days)).isoformat()

      cursor.execute("""
        SELECT text, remind_date, remind_time FROM reminders
        WHERE remind_date <= ? AND remind_date >= DATE('now')
        AND status = 'active' ORDER BY remind_date, remind_time
      """, (future,))

      return [dict(r) for r in cursor.fetchall()]
    except:
      return []
    finally:
      conn.close()

  # =====================================
  # FINANCIAL CONSCIENCE (STRICT SAVER)
  # =====================================

  def _extract_amount(self, text: str) -> Optional[float]:
    """Extract amount from text"""
    patterns = [
      r'₹\s*(\d+(?:,\d+)*(?:\.\d+)?)',
      r'rs\.?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
      r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:rupees?|rs)',
      r'(\d{4,})',
    ]
    for pat in patterns:
      match = re.search(pat, text.lower())
      if match:
        return float(match.group(1).replace(',', ''))
    return None

  def _detect_category(self, text: str) -> str:
    """Detect spending category from text"""
    text_lower = text.lower()
    keywords = self.rules.get("category_keywords", {})

    for category, words in keywords.items():
      if any(w in text_lower for w in words):
        return category

    # Default category detection
    if any(w in text_lower for w in ["food", "eat", "restaurant", "khana", "order"]):
      return "food"
    if any(w in text_lower for w in ["travel", "trip", "flight", "hotel", "yatra"]):
      return "travel"
    if any(w in text_lower for w in ["phone", "laptop", "gadget", "electronics"]):
      return "electronics"
    if any(w in text_lower for w in ["clothes", "shoes", "shopping", "kapde"]):
      return "shopping"

    return "general"

  def _is_whitelisted_category(self, category: str) -> bool:
    """Check if category bypasses strict rules"""
    whitelist = self.rules.get("financial_conscience", {}).get("approval_rules", {}).get(
      "category_whitelist", {}).get("categories", [])
    return category in whitelist

  def _calculate_risk_level(self, amount: float, balance: float, 
                upcoming_bills: float) -> RiskLevel:
    """Calculate risk level for a purchase"""
    if balance <= 0:
      return RiskLevel.CRITICAL

    # Post-spend balance
    post_spend = balance - amount
    required_buffer = upcoming_bills * 1.2  # 20% buffer

    # Risk based on % of balance and buffer safety
    spend_ratio = amount / balance
    buffer_safe = post_spend >= required_buffer

    if amount > balance or not buffer_safe:
      return RiskLevel.CRITICAL

    risk_thresholds = self.rules.get("financial_conscience", {}).get("risk_levels", {})

    if spend_ratio <= risk_thresholds.get("low", {}).get("threshold", 0.10):
      return RiskLevel.LOW
    elif spend_ratio <= risk_thresholds.get("medium", {}).get("threshold", 0.25):
      return RiskLevel.MEDIUM
    elif spend_ratio <= risk_thresholds.get("high", {}).get("threshold", 0.40):
      return RiskLevel.HIGH
    else:
      return RiskLevel.CRITICAL

  def evaluate_purchase(self, amount: float, item: str = "", 
             category: str = None) -> DecisionResult:
    """
    STRICT SAVER evaluation for a purchase.

    DEFAULT = SAY NO
    Approve only if:
    1. Post-spend > (30-day bills + 20% buffer)
    2. EMI < 30% income
    3. Category whitelisted
    """
    # Gather context
    finance = self.get_financial_state()
    obligations = self.get_upcoming_obligations(30)
    mood = self.get_emotional_state()

    if not finance.get("available"):
      return DecisionResult(
        approved=False,
        recommendation="Cannot evaluate - no financial data",
        risk_level=RiskLevel.HIGH,
        reasoning="Financial data unavailable",
        numbers={},
        tradeoffs=[],
        alternatives=["Add your accounts first"],
        action_steps=["Run: add account Cash 10000"],
        delay_plan=None,
        ride_mode_response="❓ Need financial data first"
      )

    balance = finance['balance']
    monthly_income = finance['monthly_income']
    upcoming_bills = obligations['total']
    detected_category = category or self._detect_category(item)

    # Calculate key metrics
    post_spend = balance - amount
    required_buffer = upcoming_bills * 1.2
    emi_3month = amount / 3
    emi_ratio = emi_3month / monthly_income if monthly_income else 1.0
    spend_ratio = amount / balance if balance > 0 else 1.0

    risk_level = self._calculate_risk_level(amount, balance, upcoming_bills)
    is_whitelisted = self._is_whitelisted_category(detected_category)

    # STRICT SAVER LOGIC: DEFAULT = NO
    approved = False
    reasoning_parts = []

    # Rule 1: Post-spend buffer check
    buffer_safe = post_spend >= required_buffer
    if not buffer_safe:
      reasoning_parts.append(f"After spending, balance (₹{post_spend:,.0f}) < required buffer (₹{required_buffer:,.0f})")

    # Rule 2: Amount vs balance check
    spend_limit = balance * 0.3  # 70/30 rule
    within_limit = amount <= spend_limit
    if not within_limit:
      reasoning_parts.append(f"Amount exceeds 30% spending limit (₹{spend_limit:,.0f})")

    # Rule 3: EMI check
    emi_safe = emi_ratio <= 0.30
    if not emi_safe and amount > 5000:  # Only check EMI for larger amounts
      reasoning_parts.append(f"EMI (₹{emi_3month:,.0f}/mo) > 30% income")

    # Approval conditions
    if amount > balance:
      approved = False
      reasoning_parts.insert(0, "❌ Insufficient balance")
    elif is_whitelisted and buffer_safe:
      approved = True
      reasoning_parts = [f"✅ {detected_category.title()} is priority category"]
    elif buffer_safe and within_limit and (emi_safe or amount <= 5000):
      approved = True
      reasoning_parts = ["✅ Within safe spending limits"]
    elif buffer_safe and risk_level == RiskLevel.LOW:
      approved = True
      reasoning_parts = ["✅ Low-risk small purchase"]

    # Generate response components
    numbers = {
      "amount": amount,
      "balance": balance,
      "post_spend": post_spend,
      "upcoming_bills": upcoming_bills,
      "spend_ratio_pct": spend_ratio * 100,
      "emi_3month": emi_3month,
      "emi_ratio_pct": emi_ratio * 100,
      "daily_avg": finance.get('daily_avg', 0)
    }

    tradeoffs = self._generate_tradeoffs(amount, finance, mood)
    alternatives = self._generate_alternatives(amount, item, detected_category)
    action_steps = self._generate_action_steps(approved, amount, item)
    delay_plan = self._generate_delay_plan(amount, finance) if not approved else None

    # Main recommendation
    if approved:
      rec = f"✅ Proceed with ₹{amount:,.0f} {item}"
    else:
      rec = f"❌ Hold off on ₹{amount:,.0f} {item}"

    reasoning = " | ".join(reasoning_parts) if reasoning_parts else "Evaluated against strict saver rules"

    # Ride mode response (1 sentence max)
    if approved:
      ride = f"✅ Go for it!" if risk_level == RiskLevel.LOW else f"✅ Ok, but careful."
    else:
      ride = f"❌ Not now, yaar." if risk_level == RiskLevel.CRITICAL else f"⏳ Wait karo."

    return DecisionResult(
      approved=approved,
      recommendation=rec,
      risk_level=risk_level,
      reasoning=reasoning,
      numbers=numbers,
      tradeoffs=tradeoffs,
      alternatives=alternatives,
      action_steps=action_steps,
      delay_plan=delay_plan,
      ride_mode_response=ride
    )

  def _generate_tradeoffs(self, amount: float, finance: Dict, mood: Dict) -> List[str]:
    """Generate tradeoff considerations"""
    tradeoffs = []

    daily_avg = finance.get('daily_avg', 0)
    if daily_avg > 0:
      days = amount / daily_avg
      tradeoffs.append(f"= {days:.0f} days of normal spending")

    if mood.get('is_stressed'):
      tradeoffs.append("You're stressed - emotional spending ka risk")

    save_rate = finance.get('save_rate', 0)
    if save_rate < 0.3:
      tradeoffs.append("Savings rate already low this month")

    return tradeoffs[:3]

  def _generate_alternatives(self, amount: float, item: str, category: str) -> List[str]:
    """Generate 2 alternatives"""
    alts = []

    if amount >= 5000:
      alts.append(f"Split into 3 EMIs of ₹{amount/3:,.0f}")

    if category == "food":
      alts.append("Cook at home - save ₹500+")
    elif category == "shopping":
      alts.append("Wait for sale/discount")
    elif category == "electronics":
      alts.append("Check refurbished options")
    elif category == "travel":
      alts.append("Try off-season travel")
    else:
      alts.append("Find cheaper alternative")

    if amount >= 10000:
      alts.append(f"Save for {amount//5000} weeks, then buy")

    return alts[:2]

  def _generate_action_steps(self, approved: bool, amount: float, item: str) -> List[str]:
    """Generate action steps"""
    if approved:
      return [
        f"1. Confirm ₹{amount:,.0f} {item}",
        "2. Track in expenses after",
        "3. Review month-end spending"
      ]
    else:
      return [
        "1. Add this to wishlist",
        "2. Set savings goal",
        "3. Review after 30 days"
      ]

  def _generate_delay_plan(self, amount: float, finance: Dict) -> str:
    """Generate delay/savings plan"""
    daily_save = finance.get('daily_avg', 500) * 0.2  # Save 20% of daily spend
    if daily_save < 100:
      daily_save = 100

    days_needed = amount / daily_save
    weeks = days_needed / 7

    return f"Save ₹{daily_save:.0f}/day → Buy in {weeks:.0f} weeks"

  # =====================================
  # FULL DECISION PIPELINE
  # =====================================

  def detect_domain(self, query: str) -> DecisionDomain:
    """Detect decision domain from query"""
    query_lower = query.lower()

    domain_keywords = {
      DecisionDomain.FINANCE: ["buy", "spend", "afford", "invest", "loan", "emi", "khareed", "paisa"],
      DecisionDomain.TRAVEL: ["trip", "travel", "flight", "hotel", "vacation", "yatra", "ghoomna"],
      DecisionDomain.FOOD: ["eat", "food", "order", "restaurant", "zomato", "swiggy", "khana"],
      DecisionDomain.CAREER: ["job", "work", "career", "resign", "salary", "naukri"],
      DecisionDomain.HEALTH: ["health", "doctor", "gym", "medicine", "workout", "sehat"],
      DecisionDomain.RELATIONSHIP: ["relationship", "friend", "date", "partner", "rishta"],
      DecisionDomain.LEARNING: ["learn", "course", "study", "skill", "padhna", "siksha"]
    }

    for domain, keywords in domain_keywords.items():
      if any(k in query_lower for k in keywords):
        return domain

    return DecisionDomain.GENERAL

  def full_pipeline(self, query: str, person: str = None) -> Dict[str, Any]:
    """
    Full decision pipeline:
    1. Identify domain
    2. Fetch all context
    3. Generate recommendation + tradeoffs + actions
    """
    domain = self.detect_domain(query)

    # Gather all context
    context = {
      "domain": domain.value,
      "query": query,
      "timestamp": datetime.now().isoformat(),
      "finances": self.get_financial_state(),
      "habits": self.get_habit_state(),
      "mood": self.get_emotional_state(),
      "reminders": self.get_pending_reminders(7),
      "past_outcomes": self.get_past_outcomes(domain.value, 3),
      "obligations": self.get_upcoming_obligations(30)
    }

    # Extract amount if financial query
    amount = self._extract_amount(query)

    # Generate decision
    if amount and domain in [DecisionDomain.FINANCE, DecisionDomain.TRAVEL, 
                  DecisionDomain.FOOD, DecisionDomain.LEARNING]:
      result = self.evaluate_purchase(amount, query)
      context["decision"] = {
        "approved": result.approved,
        "recommendation": result.recommendation,
        "risk_level": result.risk_level.value,
        "reasoning": result.reasoning,
        "numbers": result.numbers,
        "tradeoffs": result.tradeoffs,
        "alternatives": result.alternatives,
        "action_steps": result.action_steps,
        "delay_plan": result.delay_plan,
        "ride_mode": result.ride_mode_response
      }
    else:
      # Non-financial decision
      context["decision"] = self._evaluate_general(query, context)

    return context

  def _evaluate_general(self, query: str, context: Dict) -> Dict[str, Any]:
    """Evaluate non-financial decisions"""
    mood = context.get("mood", {})
    habits = context.get("habits", {})

    recommendation = "Consider it carefully"
    tradeoffs = []

    if mood.get('is_stressed'):
      tradeoffs.append("High stress - avoid big decisions today")
    if mood.get('is_low_energy'):
      tradeoffs.append("Low energy - postpone if possible")
    if habits.get('streaks_at_risk'):
      tradeoffs.append(f"Habit pending: {habits['streaks_at_risk'][0]}")

    return {
      "approved": None,  # Needs user judgment
      "recommendation": recommendation,
      "tradeoffs": tradeoffs,
      "action_steps": ["Think it through", "Sleep on it if big decision"]
    }

  # =====================================
  # RESPONSE FORMATTING
  # =====================================

  def format_decision(self, result: DecisionResult, ride_mode: bool = False) -> str:
    """Format decision result for display"""
    if ride_mode:
      return result.ride_mode_response

    lines = []

    # Risk emoji and verdict
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    emoji = risk_emoji.get(result.risk_level.value, "🤔")

    # Explicit verdict: APPROVED / CAUTION / DENIED
    if result.approved and result.risk_level == RiskLevel.LOW:
      verdict = "✅ APPROVED"
    elif result.approved:
      verdict = "⚠️ CAUTION"
    else:
      verdict = "❌ DENIED"

    # Header with verdict
    lines.append(f"{verdict}\n")
    lines.append(f"{emoji} **{result.recommendation}**\n")

    # Numbers
    lines.append("**Numbers:**")
    n = result.numbers
    lines.append(f"  Balance: ₹{n.get('balance', 0):,.0f} → ₹{n.get('post_spend', 0):,.0f}")
    lines.append(f"  This is {n.get('spend_ratio_pct', 0):.0f}% of your money")
    if n.get('upcoming_bills', 0) > 0:
      lines.append(f"  Upcoming bills: ₹{n['upcoming_bills']:,.0f}")

    # Risk
    lines.append(f"\n**Risk Level:** {emoji} {result.risk_level.value.upper()}")
    lines.append(f"**Why:** {result.reasoning}")

    # Tradeoffs
    if result.tradeoffs:
      lines.append("\n**Trade-offs:**")
      for t in result.tradeoffs:
        lines.append(f"  • {t}")

    # Alternatives
    if result.alternatives:
      lines.append("\n**Alternatives:**")
      for a in result.alternatives:
        lines.append(f"  → {a}")

    # Delay plan
    if result.delay_plan:
      lines.append(f"\n**Delay Plan:** {result.delay_plan}")

    # Action steps
    if result.action_steps:
      lines.append("\n**Next Steps:**")
      for s in result.action_steps:
        lines.append(f"  {s}")

    return "\n".join(lines)

  def format_pipeline_result(self, pipeline: Dict, ride_mode: bool = False) -> str:
    """Format full pipeline result"""
    decision = pipeline.get("decision", {})

    if ride_mode:
      return decision.get("ride_mode", "🤔 Think about it")

    lines = []

    # Domain
    domain = pipeline.get("domain", "general")
    lines.append(f"**Decision: {domain.upper()}**\n")

    # Recommendation
    rec = decision.get("recommendation", "No clear recommendation")
    lines.append(f"**→ {rec}**")

    # Quick context
    mood = pipeline.get("mood", {})
    if mood.get("mood"):
      lines.append(f"\nMood: {mood['mood']} | Energy: {'⚡' * min(mood.get('energy', 5), 5)}")

    # Tradeoffs
    if decision.get("tradeoffs"):
      lines.append("\n**Consider:**")
      for t in decision["tradeoffs"][:3]:
        lines.append(f"  ⚖️ {t}")

    # Action steps
    if decision.get("action_steps"):
      lines.append("\n**Actions:**")
      for s in decision["action_steps"][:3]:
        lines.append(f"  → {s}")

    return "\n".join(lines)
