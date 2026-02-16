"""
PHASE 12: Decision Engine - Contextual Advice with Self-Model

Before giving advice, checks:
1. Financial state (can you afford it?)
2. Habit patterns (will this break your streak?)
3. Past decisions (what worked before?)
4. Personality profile (matches your style?)
5. Current mood (timing right?)
6. Relation context (who's involved?)
7. Upcoming bills/reminders (spending safety)
8. Life planning (daily schedule)
"""
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, date, timedelta
import sqlite3
import json
import re


class DecisionEngine:
    """
    Contextual decision support engine.
    
    Gathers full context before suggesting advice:
    - Finance: balance, recent spending patterns
    - Habits: active habits, streaks at risk
    - Decisions: past outcomes in similar domains
    - Persona: risk tolerance, decision style
    - Mood: current emotional state
    - Relations: people involved and context
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
    
    def _conn(self, db_name: str):
        """Get DB connection"""
        path = self.data_dir / db_name
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # =====================================
    # CONTEXT GATHERING
    # =====================================
    
    def get_financial_context(self) -> Dict[str, Any]:
        """Get current financial state for decision context"""
        conn = self._conn("finance.db")
        if not conn:
            return {"available": False}
        
        try:
            cursor = conn.cursor()
            
            # Total balance across accounts
            cursor.execute("SELECT COALESCE(SUM(balance), 0) as total FROM accounts")
            total = cursor.fetchone()['total']
            
            # Recent spending (last 30 days)
            cursor.execute("""
                SELECT COALESCE(SUM(ABS(amount)), 0) as spent
                FROM transactions
                WHERE type = 'expense' AND date >= DATE('now', '-30 days')
            """)
            recent_spending = cursor.fetchone()['spent']
            
            # Top spending categories
            cursor.execute("""
                SELECT category, SUM(ABS(amount)) as total
                FROM transactions
                WHERE type = 'expense' AND date >= DATE('now', '-30 days')
                GROUP BY category ORDER BY total DESC LIMIT 3
            """)
            top_categories = [{"category": r['category'], "amount": r['total']} for r in cursor.fetchall()]
            
            return {
                "available": True,
                "total_balance": total,
                "recent_spending_30d": recent_spending,
                "top_categories": top_categories,
                "is_low_balance": total < 5000,  # Threshold for low balance warning
                "avg_daily_spend": recent_spending / 30 if recent_spending else 0
            }
        finally:
            conn.close()
    
    def get_habit_context(self) -> Dict[str, Any]:
        """Get habit state for decision context"""
        conn = self._conn("habits.db")
        if not conn:
            return {"available": False}
        
        try:
            cursor = conn.cursor()
            
            # Active habits
            cursor.execute("""
                SELECT h.name, h.frequency, 
                       (SELECT MAX(done_date) FROM habit_logs WHERE habit_id = h.id) as last_done
                FROM habits h WHERE h.status = 'active'
            """)
            habits = []
            streaks_at_risk = []
            today = date.today().isoformat()
            
            for r in cursor.fetchall():
                habit = {"name": r['name'], "frequency": r['frequency'], "last_done": r['last_done']}
                habits.append(habit)
                
                # Check if streak at risk (not done today for daily)
                if r['frequency'] == 'daily' and r['last_done'] != today:
                    streaks_at_risk.append(r['name'])
            
            return {
                "available": True,
                "active_habits": habits,
                "count": len(habits),
                "streaks_at_risk": streaks_at_risk,
                "has_active_habits": len(habits) > 0
            }
        except Exception:
            return {"available": False}
        finally:
            conn.close()
    
    def get_decision_history(self, domain: str = None, limit: int = 5) -> Dict[str, Any]:
        """Get past decisions and outcomes for learning"""
        conn = self._conn("persona.db")
        if not conn:
            return {"available": False}
        
        try:
            cursor = conn.cursor()
            
            if domain:
                cursor.execute("""
                    SELECT * FROM decision_log 
                    WHERE LOWER(domain) = LOWER(?)
                    ORDER BY decision_date DESC LIMIT ?
                """, (domain, limit))
            else:
                cursor.execute("""
                    SELECT * FROM decision_log 
                    ORDER BY decision_date DESC LIMIT ?
                """, (limit,))
            
            rows = cursor.fetchall()
            decisions = []
            good_outcomes = 0
            bad_outcomes = 0
            
            for r in rows:
                decisions.append({
                    "date": r['decision_date'],
                    "domain": r['domain'],
                    "situation": r['situation'],
                    "decision": r['decision_made'],
                    "outcome": r['outcome'],
                    "lesson": r['lesson_learned']
                })
                if r['outcome'] == 'good':
                    good_outcomes += 1
                elif r['outcome'] == 'bad':
                    bad_outcomes += 1
            
            return {
                "available": True,
                "decisions": decisions,
                "count": len(decisions),
                "good_outcomes": good_outcomes,
                "bad_outcomes": bad_outcomes,
                "success_rate": good_outcomes / len(decisions) if decisions else 0
            }
        except Exception:
            return {"available": False}
        finally:
            conn.close()
    
    def get_persona_context(self) -> Dict[str, Any]:
        """Get personality/decision style profile"""
        conn = self._conn("persona.db")
        if not conn:
            return {"available": False}
        
        try:
            cursor = conn.cursor()
            
            # Decision profile
            cursor.execute("SELECT dimension, score FROM decision_profile")
            profile = {r['dimension']: r['score'] for r in cursor.fetchall()}
            
            # Core values
            cursor.execute("SELECT value FROM personal_values ORDER BY importance DESC LIMIT 5")
            values = [r['value'] for r in cursor.fetchall()]
            
            # Traits
            cursor.execute("SELECT key, value FROM traits")
            traits = {r['key']: r['value'] for r in cursor.fetchall()}
            
            return {
                "available": True,
                "decision_profile": profile,
                "core_values": values,
                "traits": traits,
                "risk_tolerance": profile.get("risk_tolerance", 0.5),
                "is_impulsive": profile.get("impulsive_vs_deliberate", 0.5) < 0.4,
                "is_frugal": profile.get("frugal_vs_spender", 0.5) < 0.4
            }
        except Exception:
            return {"available": False}
        finally:
            conn.close()
    
    def get_emotional_context(self) -> Dict[str, Any]:
        """Get current emotional state"""
        conn = self._conn("persona.db")
        if not conn:
            return {"available": False, "mood": "neutral", "mood_score": 5, "energy": 5, "stress": 3}
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mood, mood_score, energy_level, stress_level, trigger
                FROM emotional_state 
                ORDER BY log_date DESC, log_time DESC LIMIT 1
            """)
            row = cursor.fetchone()
            
            if row:
                return {
                    "available": True,
                    "mood": row['mood'],
                    "mood_score": row['mood_score'],
                    "energy": row['energy_level'],
                    "stress": row['stress_level'],
                    "trigger": row['trigger'],
                    "is_stressed": row['stress_level'] >= 7,
                    "is_low_energy": row['energy_level'] <= 3,
                    "is_positive": row['mood_score'] >= 7
                }
            return {"available": False, "mood": "unknown"}
        except Exception:
            return {"available": False}
        finally:
            conn.close()
    
    def get_relation_context(self, person_name: str) -> Dict[str, Any]:
        """Get relationship context for person-sensitive decisions"""
        conn = self._conn("relations.db")
        if not conn:
            return {"available": False}
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM relations WHERE LOWER(name) LIKE ?
            """, (f"%{person_name.lower()}%",))
            row = cursor.fetchone()
            
            if not row:
                return {"available": False, "person": person_name}
            
            # Get interaction history
            cursor.execute("""
                SELECT interaction_date, summary 
                FROM interactions WHERE person_id = ?
                ORDER BY interaction_date DESC LIMIT 5
            """, (row['id'],))
            history = [{"date": r['interaction_date'], "summary": r['summary']} for r in cursor.fetchall()]
            
            # Check for per-person context columns (Phase 12 additions)
            talk_style = None
            topics_avoid = None
            try:
                cursor.execute("SELECT talk_style, topics_to_avoid FROM relations WHERE id = ?", (row['id'],))
                ctx = cursor.fetchone()
                if ctx:
                    talk_style = ctx['talk_style']
                    topics_avoid = ctx['topics_to_avoid']
            except:
                pass  # Columns not yet added
            
            return {
                "available": True,
                "name": row['name'],
                "relationship": row['relationship'],
                "trust_level": row['trust_level'],
                "notes": row['notes'],
                "last_contact": row['last_contact'],
                "history": history,
                "talk_style": talk_style,
                "topics_to_avoid": topics_avoid,
                "is_close": row['trust_level'] >= 7,
                "is_formal": row['relationship'] in ['boss', 'client', 'colleague']
            }
        except Exception as e:
            return {"available": False, "error": str(e)}
        finally:
            conn.close()
    
    # =====================================
    # FULL CONTEXT GATHERING
    # =====================================
    
    def gather_full_context(self, query: str = "", person_involved: str = None) -> Dict[str, Any]:
        """
        Gather ALL relevant context for decision-making.
        
        Returns a comprehensive context dictionary that can be used
        by the LLM to give personalized, context-aware advice.
        """
        context = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "financial": self.get_financial_context(),
            "habits": self.get_habit_context(),
            "past_decisions": self.get_decision_history(limit=5),
            "persona": self.get_persona_context(),
            "emotional": self.get_emotional_context()
        }
        
        if person_involved:
            context["relation"] = self.get_relation_context(person_involved)
        
        # Generate warnings
        context["warnings"] = self._generate_warnings(context)
        
        # Generate recommendations
        context["recommendations"] = self._generate_recommendations(context, query)
        
        return context
    
    def _generate_warnings(self, context: Dict[str, Any]) -> List[str]:
        """Generate warning flags based on context"""
        warnings = []
        
        # Financial warnings
        fin = context.get("financial", {})
        if fin.get("is_low_balance"):
            warnings.append("LOW_BALANCE: Consider financial impact carefully")
        
        # Habit warnings
        habits = context.get("habits", {})
        if habits.get("streaks_at_risk"):
            warnings.append(f"STREAK_AT_RISK: {', '.join(habits['streaks_at_risk'])}")
        
        # Emotional warnings
        emotional = context.get("emotional", {})
        if emotional.get("is_stressed"):
            warnings.append("HIGH_STRESS: May not be best time for big decisions")
        if emotional.get("is_low_energy"):
            warnings.append("LOW_ENERGY: Consider postponing demanding activities")
        
        # Persona warnings
        persona = context.get("persona", {})
        if persona.get("is_impulsive"):
            warnings.append("IMPULSIVE_TENDENCY: Take a moment to think this through")
        
        return warnings
    
    def _generate_recommendations(self, context: Dict[str, Any], query: str) -> List[str]:
        """Generate personalized recommendations"""
        recs = []
        query_lower = query.lower()
        
        # Financial recommendations
        fin = context.get("financial", {})
        if any(word in query_lower for word in ["buy", "spend", "purchase", "khareedna"]):
            if fin.get("is_low_balance"):
                recs.append("Your balance is low - consider waiting or finding alternatives")
            if fin.get("avg_daily_spend", 0) > 0:
                recs.append(f"Your average daily spend is Rs {fin['avg_daily_spend']:.0f}")
        
        # Habit-aware recommendations
        habits = context.get("habits", {})
        if habits.get("streaks_at_risk"):
            recs.append(f"Don't forget: {habits['streaks_at_risk'][0]} streak needs attention!")
        
        # Past decisions learning
        past = context.get("past_decisions", {})
        if past.get("available") and past.get("decisions"):
            # Look for similar situations
            for d in past["decisions"]:
                if d.get("lesson"):
                    recs.append(f"Past lesson ({d['domain']}): {d['lesson']}")
                    break
        
        # Mood-aware recommendations
        emotional = context.get("emotional", {})
        if emotional.get("is_stressed"):
            recs.append("You seem stressed - prioritize self-care today")
        if emotional.get("is_positive"):
            recs.append("Good energy! Great time for tackling challenges")
        
        return recs[:3]  # Return top 3 recommendations
    
    # =====================================
    # ADVICE GENERATION HELPERS
    # =====================================
    
    def should_approve_purchase(self, amount: float) -> Dict[str, Any]:
        """Should this purchase be approved based on financial context?"""
        fin = self.get_financial_context()
        persona = self.get_persona_context()
        emotional = self.get_emotional_context()
        
        if not fin.get("available"):
            return {"approve": None, "reason": "No financial data available"}
        
        balance = fin.get("total_balance", 0)
        daily_avg = fin.get("avg_daily_spend", 0)
        is_frugal = persona.get("is_frugal", False)
        is_stressed = emotional.get("is_stressed", False)
        
        # Decision logic
        if amount > balance:
            return {"approve": False, "reason": f"Amount exceeds balance (Rs {balance:.0f})"}
        
        if amount > balance * 0.3:
            reason = f"This is {amount/balance*100:.0f}% of your total balance"
            if is_frugal:
                return {"approve": False, "reason": reason + " - consider smaller alternatives"}
            return {"approve": "caution", "reason": reason}
        
        if amount > daily_avg * 7:
            return {"approve": "caution", "reason": f"This equals {amount/daily_avg:.0f} days of typical spending"}
        
        if is_stressed:
            return {"approve": "caution", "reason": "You're stressed - sleep on it?"}
        
        return {"approve": True, "reason": "Looks manageable"}
    
    def get_advice_context_prompt(self, query: str, person: str = None) -> str:
        """
        Generate a context prompt for LLM to give personalized advice.
        
        This is injected into the system prompt so the LLM knows
        about the user's full context.
        """
        ctx = self.gather_full_context(query, person)
        
        lines = ["DECISION CONTEXT FOR THIS QUERY:"]
        
        # Financial
        fin = ctx.get("financial", {})
        if fin.get("available"):
            lines.append(f"- Finance: Balance Rs {fin['total_balance']:.0f}, "
                        f"30-day spending Rs {fin['recent_spending_30d']:.0f}")
        
        # Habits
        habits = ctx.get("habits", {})
        if habits.get("available"):
            lines.append(f"- Habits: {habits['count']} active, "
                        f"at risk: {', '.join(habits['streaks_at_risk']) or 'none'}")
        
        # Mood
        emotional = ctx.get("emotional", {})
        if emotional.get("available"):
            lines.append(f"- Mood: {emotional['mood']} (energy: {emotional['energy']}/10, "
                        f"stress: {emotional['stress']}/10)")
        
        # Persona
        persona = ctx.get("persona", {})
        if persona.get("available"):
            risk = "risk-taking" if persona['risk_tolerance'] > 0.6 else "cautious"
            lines.append(f"- Style: {risk}, values: {', '.join(persona['core_values'][:3]) or 'not set'}")
        
        # Relation (if person involved)
        if person and ctx.get("relation", {}).get("available"):
            rel = ctx["relation"]
            lines.append(f"- Re {rel['name']}: {rel['relationship']} (trust: {rel['trust_level']}/10)")
        
        # Warnings
        if ctx.get("warnings"):
            lines.append(f"- WARNINGS: {'; '.join(ctx['warnings'])}")
        
        # Recommendations
        if ctx.get("recommendations"):
            lines.append(f"- RECS: {'; '.join(ctx['recommendations'])}")
        
        return "\n".join(lines)
    
    def format_context_summary(self) -> str:
        """Format a human-readable context summary"""
        ctx = self.gather_full_context()
        
        parts = []
        
        # Financial
        fin = ctx.get("financial", {})
        if fin.get("available"):
            parts.append(f"Balance: Rs {fin['total_balance']:,.0f}")
        
        # Mood
        emotional = ctx.get("emotional", {})
        if emotional.get("available"):
            parts.append(f"Mood: {emotional['mood']}")
        
        # Habits at risk
        habits = ctx.get("habits", {})
        if habits.get("streaks_at_risk"):
            parts.append(f"Pending: {habits['streaks_at_risk'][0]}")
        
        return " | ".join(parts) if parts else "Context: default"
    
    # =====================================
    # FINANCE GUARD (Phase 12 Enhanced)
    # =====================================
    
    def get_upcoming_bills(self, days: int = 30) -> Dict[str, Any]:
        """Get upcoming bills/reminders that need money"""
        conn = self._conn("reminders.db")
        if not conn:
            return {"available": False, "bills": [], "total": 0}
        
        try:
            cursor = conn.cursor()
            future_date = (date.today() + timedelta(days=days)).isoformat()
            
            cursor.execute("""
                SELECT text, remind_date, remind_time
                FROM reminders 
                WHERE remind_date <= ? AND remind_date >= DATE('now')
                AND status = 'active'
                AND (LOWER(text) LIKE '%bill%' OR LOWER(text) LIKE '%pay%' 
                     OR LOWER(text) LIKE '%emi%' OR LOWER(text) LIKE '%rent%'
                     OR LOWER(text) LIKE '%fee%' OR LOWER(text) LIKE '%bharna%')
                ORDER BY remind_date
            """, (future_date,))
            
            bills = []
            for r in cursor.fetchall():
                # Try to extract amount from text
                amount = self._extract_amount(r['text'])
                bills.append({
                    "text": r['text'],
                    "date": r['remind_date'],
                    "amount": amount
                })
            
            total_bills = sum(b['amount'] for b in bills if b['amount'])
            
            return {
                "available": True,
                "bills": bills,
                "count": len(bills),
                "total_estimated": total_bills
            }
        except Exception:
            return {"available": False, "bills": [], "total": 0}
        finally:
            conn.close()
    
    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract amount from text like 'pay rent 15000' or 'EMI Rs 5000'"""
        patterns = [
            r'₹\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'rs\.?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:rupees?|rs)',
            r'(\d{4,})',  # 4+ digit numbers likely amounts
        ]
        for pat in patterns:
            match = re.search(pat, text.lower())
            if match:
                return float(match.group(1).replace(',', ''))
        return None
    
    def analyze_purchase(self, amount: float, item: str = "") -> Dict[str, Any]:
        """
        Full Finance Guard analysis for a purchase.
        
        Returns:
        - affordability_pct: what % of balance this is
        - impact_30d: how it affects next 30 days
        - emi_safe: if splitting into EMI is safe
        - recommendation: buy/wait/split
        - reasoning: short explanation
        """
        fin = self.get_financial_context()
        bills = self.get_upcoming_bills(30)
        persona = self.get_persona_context()
        emotional = self.get_emotional_context()
        
        if not fin.get("available"):
            return {
                "can_analyze": False,
                "recommendation": "unknown",
                "reasoning": "No financial data available"
            }
        
        balance = fin.get("total_balance", 0)
        monthly_spend = fin.get("recent_spending_30d", 0)
        daily_avg = fin.get("avg_daily_spend", 0)
        upcoming_bills = bills.get("total_estimated", 0)
        is_frugal = persona.get("is_frugal", False)
        is_stressed = emotional.get("is_stressed", False)
        
        # Calculations
        affordability_pct = (amount / balance * 100) if balance > 0 else 100
        available_after_bills = balance - upcoming_bills
        safe_to_spend = available_after_bills - (daily_avg * 30)  # Leave 30 days cushion
        
        # EMI calculation (3 month split)
        emi_amount = amount / 3
        emi_safe = emi_amount < (balance * 0.15)  # EMI should be < 15% of balance
        
        # Impact analysis
        days_of_spending = amount / daily_avg if daily_avg > 0 else 0
        
        # Decision logic
        warnings = []
        if affordability_pct > 50:
            warnings.append(f"This is {affordability_pct:.0f}% of your balance!")
        if amount > safe_to_spend:
            warnings.append(f"After bills, you have only Rs {available_after_bills:.0f}")
        if bills.get("count", 0) > 0:
            warnings.append(f"{bills['count']} bills coming up (Rs {upcoming_bills:.0f})")
        if is_stressed:
            warnings.append("You're stressed - emotional purchases regret hota hai")
        
        # Recommendation
        if amount > balance:
            recommendation = "cannot_afford"
            reasoning = f"Amount exceeds balance (Rs {balance:.0f})"
            alternatives = ["Save for it", "Find cheaper options", "Wait for next month"]
        elif amount > available_after_bills:
            recommendation = "wait"
            reasoning = f"Bills coming up will leave only Rs {available_after_bills - amount:.0f}"
            alternatives = ["Wait until after bills", "Split into smaller purchases"]
        elif affordability_pct > 30:
            if is_frugal:
                recommendation = "split"
                reasoning = f"This is {affordability_pct:.0f}% of balance - split karo"
                alternatives = [f"3 EMIs of Rs {emi_amount:.0f}", "Wait 2 weeks", "Budget cut elsewhere"]
            else:
                recommendation = "caution"
                reasoning = f"Big purchase - think for a day"
                alternatives = ["Sleep on it", "Check for discounts"]
        else:
            recommendation = "approved"
            reasoning = "Affordable and won't impact upcoming expenses"
            alternatives = []
        
        return {
            "can_analyze": True,
            "amount": amount,
            "item": item,
            "affordability_pct": round(affordability_pct, 1),
            "balance": balance,
            "available_after_bills": available_after_bills,
            "upcoming_bills": upcoming_bills,
            "days_of_spending": round(days_of_spending, 1),
            "emi_amount": round(emi_amount, 0),
            "emi_safe": emi_safe,
            "recommendation": recommendation,
            "reasoning": reasoning,
            "warnings": warnings,
            "alternatives": alternatives
        }
    
    def format_purchase_analysis(self, amount: float, item: str = "") -> str:
        """Format purchase analysis as readable response"""
        analysis = self.analyze_purchase(amount, item)
        
        if not analysis.get("can_analyze"):
            return analysis.get("reasoning", "Cannot analyze")
        
        lines = []
        
        # Header with recommendation
        rec = analysis["recommendation"]
        emoji = {"approved": "✅", "caution": "⚠️", "wait": "⏳", "split": "📊", "cannot_afford": "❌"}.get(rec, "🤔")
        item_text = f" for {item}" if item else ""
        lines.append(f"{emoji} **Rs {amount:,.0f}{item_text}**")
        
        # Key metrics
        lines.append(f"\nAffordability: {analysis['affordability_pct']}% of balance")
        lines.append(f"Balance after: Rs {analysis['balance'] - amount:,.0f}")
        if analysis['upcoming_bills'] > 0:
            lines.append(f"Upcoming bills: Rs {analysis['upcoming_bills']:,.0f}")
        lines.append(f"= {analysis['days_of_spending']} days of typical spending")
        
        # Reasoning
        lines.append(f"\n**Verdict:** {analysis['reasoning']}")
        
        # Warnings
        if analysis['warnings']:
            lines.append("\n**Dhyan do:**")
            for w in analysis['warnings']:
                lines.append(f"  ⚠️ {w}")
        
        # Alternatives
        if analysis['alternatives']:
            lines.append("\n**Alternatives:**")
            for a in analysis['alternatives']:
                lines.append(f"  → {a}")
        
        return "\n".join(lines)
    
    # =====================================
    # LIFE PLANNING (Phase 12 Enhanced)
    # =====================================
    
    def get_daily_plan(self, target_date: date = None) -> Dict[str, Any]:
        """
        Generate daily plan based on:
        - Active habits to do
        - Reminders for the day
        - Current energy level
        - Work hours preference
        """
        target_date = target_date or date.today()
        date_str = target_date.isoformat()
        
        plan = {
            "date": date_str,
            "habits_pending": [],
            "habits_done": [],
            "reminders": [],
            "energy_level": 5,
            "suggested_schedule": []
        }
        
        # Get habits
        habits_ctx = self.get_habit_context()
        if habits_ctx.get("available"):
            for h in habits_ctx.get("active_habits", []):
                if h.get("last_done") == date_str:
                    plan["habits_done"].append(h["name"])
                else:
                    plan["habits_pending"].append(h["name"])
        
        # Get reminders
        conn = self._conn("reminders.db")
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT text, remind_time FROM reminders
                    WHERE remind_date = ? AND status = 'active'
                    ORDER BY remind_time
                """, (date_str,))
                
                for r in cursor.fetchall():
                    plan["reminders"].append({
                        "text": r['text'],
                        "time": r['remind_time']
                    })
            except:
                pass
            finally:
                conn.close()
        
        # Get energy level
        emotional = self.get_emotional_context()
        if emotional.get("available"):
            plan["energy_level"] = emotional.get("energy", 5)
            plan["mood"] = emotional.get("mood", "neutral")
            plan["stress"] = emotional.get("stress", 3)
        
        # Generate suggested schedule
        plan["suggested_schedule"] = self._generate_schedule(plan)
        
        return plan
    
    def _generate_schedule(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate a suggested schedule based on plan data"""
        schedule = []
        energy = plan.get("energy_level", 5)
        
        # Morning habits (if energy okay)
        if energy >= 4:
            for habit in plan.get("habits_pending", [])[:2]:
                schedule.append({
                    "time": "morning",
                    "activity": f"🏃 {habit}",
                    "priority": "high"
                })
        
        # Reminders with times
        for rem in plan.get("reminders", []):
            time_str = rem.get("time", "")
            slot = "day"
            if time_str:
                try:
                    hour = int(time_str.split(":")[0])
                    if hour < 12:
                        slot = "morning"
                    elif hour < 17:
                        slot = "afternoon"
                    else:
                        slot = "evening"
                except:
                    pass
            schedule.append({
                "time": slot,
                "activity": f"📌 {rem['text']}",
                "priority": "scheduled"
            })
        
        # Remaining habits for evening (if energy okay)
        if energy >= 3:
            for habit in plan.get("habits_pending", [])[2:]:
                schedule.append({
                    "time": "evening",
                    "activity": f"🏃 {habit}",
                    "priority": "medium"
                })
        
        # Low energy advice
        if energy <= 3:
            schedule.append({
                "time": "any",
                "activity": "😴 Rest priority - energy low hai",
                "priority": "self-care"
            })
        
        return schedule
    
    def format_daily_plan(self, target_date: date = None) -> str:
        """Format daily plan as readable response"""
        plan = self.get_daily_plan(target_date)
        
        lines = []
        
        # Header
        date_str = plan["date"]
        lines.append(f"📅 **Plan for {date_str}**\n")
        
        # Status
        mood_emoji = {"happy": "😊", "stressed": "😰", "anxious": "😟", "excited": "🤩", "neutral": "😐"}.get(plan.get("mood", "neutral"), "😐")
        lines.append(f"Mood: {mood_emoji} {plan.get('mood', 'neutral')} | Energy: {'⚡' * min(plan['energy_level'], 10)}")
        
        # Habits status
        done = len(plan["habits_done"])
        pending = len(plan["habits_pending"])
        lines.append(f"Habits: {done}✅ done, {pending}⏳ pending")
        
        # Schedule
        if plan["suggested_schedule"]:
            lines.append("\n**Today's Schedule:**")
            
            # Group by time
            for slot in ["morning", "afternoon", "evening", "day", "any"]:
                slot_items = [s for s in plan["suggested_schedule"] if s["time"] == slot]
                if slot_items:
                    for item in slot_items:
                        lines.append(f"  {item['activity']}")
        
        # Pending habits
        if plan["habits_pending"]:
            lines.append(f"\n**Pending:** {', '.join(plan['habits_pending'])}")
        
        # Completed
        if plan["habits_done"]:
            lines.append(f"**Done:** {', '.join(plan['habits_done'])} ✓")
        
        return "\n".join(lines)
