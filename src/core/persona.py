"""
Persona Generator - Buddy tone responses with Hinglish flavor
Formats outputs for plan, report, ask commands
"""
import random
from typing import Dict, List, Optional
from datetime import datetime


class PersonaGenerator:
    """Generates responses with buddy personality
    
    - 70% English, 30% Hindi (Hinglish)
    - Casual, friendly tone
    - Contextual formatting for different output types
    """
    
    def __init__(self):
        self.name = "TAPAN"
        
        # Hindi phrases for sprinkling
        self.hindi_phrases = {
            'greeting': ['Namaste!', 'Kya haal hai?', 'Arre bhai!', 'Hello yaar!'],
            'positive': ['Bahut badhiya!', 'Mast hai!', 'Ekdum sahi!', 'Zabardast!'],
            'acknowledge': ['Achha', 'Theek hai', 'Samajh gaya', 'Haan bhai'],
            'encourage': ['Koi baat nahi', 'Ho jayega', 'Chinta mat kar', 'Sab theek'],
            'farewell': ['Phir milenge!', 'Alvida!', 'Take care yaar!', 'Bye bhai!'],
            'time': {
                'morning': 'Good morning! ☀️',
                'afternoon': 'Good afternoon! 🌤️',
                'evening': 'Good evening! 🌙',
                'night': 'Ab so jao! 😴'
            }
        }
        
        # Response templates
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, List[str]]:
        """Load response templates"""
        return {
            'plan_intro': [
                "📅 **Aaj ka Plan** - {date}\n\n",
                "🌟 **Today's Agenda** - {date}\n\n",
                "📋 **Daily Plan** - {date}\nChalo dekho aaj kya hai!\n\n"
            ],
            'plan_reminders': [
                "⏰ **Reminders** ({count} pending)\n",
                "🔔 **Yaad Rakhna** ({count} tasks)\n"
            ],
            'plan_habits': [
                "✅ **Habits to Complete**\n",
                "💪 **Aaj ke Habits**\n"
            ],
            'plan_finance': [
                "💰 **Finance Snapshot**\n",
                "💵 **Paisa Status**\n"
            ],
            'plan_suggestion': [
                "\n💡 **Pro Tip:** {tip}",
                "\n🎯 **Suggestion:** {tip}"
            ],
            'report_intro': [
                "📊 **TAPAN LIFE REPORT**\n{'='*50}\n\n",
                "📈 **Your Life at a Glance**\n{'='*50}\n\n"
            ],
            'ask_intro': [
                "🤔 Let me check that for you...\n\n",
                "Hmm, dekho maine kya dhundha:\n\n",
                "Yeh raha aapka answer:\n\n"
            ],
            'ask_no_result': [
                "😅 Kuch specific nahi mila. Try 'search <keyword>'",
                "Hmm, yeh toh nahi hai mere paas. 'help' type karo?",
                "Arre, yeh toh dhundh nahi paya. Kuch aur try karo!"
            ],
            'success': [
                "✓ {action} - Done! 🎉",
                "✓ {action} - Ho gaya! ✨",
                "✓ {action} - Sorted! 👍"
            ],
            'error': [
                "❌ {error} - Oops!",
                "😬 {error} - Kuch gadbad hui",
                "❌ {error} - Try again?"
            ]
        }
    
    def _random_template(self, category: str, **kwargs) -> str:
        """Get random template with formatting"""
        templates = self.templates.get(category, ["{text}"])
        template = random.choice(templates)
        return template.format(**kwargs) if kwargs else template
    
    def _time_greeting(self) -> str:
        """Get time-appropriate greeting"""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return self.hindi_phrases['time']['morning']
        elif 12 <= hour < 17:
            return self.hindi_phrases['time']['afternoon']
        elif 17 <= hour < 21:
            return self.hindi_phrases['time']['evening']
        else:
            return self.hindi_phrases['time']['night']
    
    def _sprinkle_hindi(self, text: str, intensity: float = 0.3) -> str:
        """Sprinkle Hindi phrases into text (30% default)"""
        # For now, just return text - can enhance later
        return text
    
    def format_plan(self, plan_data: Dict) -> str:
        """Format daily plan with persona
        
        Args:
            plan_data: Dict with reminders, habits, finance, suggestions
        
        Returns:
            Formatted plan string
        """
        date_str = datetime.now().strftime('%A, %B %d, %Y')
        output = self._random_template('plan_intro', date=date_str)
        
        # Time greeting
        output += f"{self._time_greeting()}\n\n"
        
        # Reminders
        reminders = plan_data.get('reminders', [])
        if reminders:
            output += self._random_template('plan_reminders', count=len(reminders))
            for r in reminders[:5]:
                text = r.get('text', r) if isinstance(r, dict) else str(r)
                output += f"  • {text}\n"
            output += "\n"
        
        # Habits
        habits = plan_data.get('habits', [])
        if habits:
            output += self._random_template('plan_habits')
            for h in habits[:5]:
                name = h.get('name', h) if isinstance(h, dict) else str(h)
                streak = h.get('streak', 0) if isinstance(h, dict) else 0
                streak_str = f" 🔥{streak}" if streak > 0 else ""
                output += f"  ☐ {name}{streak_str}\n"
            output += "\n"
        
        # Finance snapshot
        finance = plan_data.get('finance', {})
        if finance:
            output += self._random_template('plan_finance')
            if 'balance' in finance:
                output += f"  Balance: ₹{finance['balance']:,.0f}\n"
            if 'today_expense' in finance:
                output += f"  Today: ₹{finance['today_expense']:,.0f} spent\n"
            if 'month_expense' in finance:
                output += f"  This Month: ₹{finance['month_expense']:,.0f}\n"
            output += "\n"
        
        # Suggestion
        suggestions = plan_data.get('suggestions', [])
        if suggestions:
            tip = random.choice(suggestions)
            output += self._random_template('plan_suggestion', tip=tip)
        
        return output
    
    def format_report(self, report_data: Dict) -> str:
        """Format life report with persona
        
        Args:
            report_data: Dict with finance, journal, habits, memories
        
        Returns:
            Formatted report string
        """
        output = self._random_template('report_intro')
        output = output.replace("{'='*50}", "=" * 50)
        
        # Finance Section
        finance = report_data.get('finance', {})
        output += "💰 **FINANCE**\n"
        output += "-" * 30 + "\n"
        if finance:
            output += f"  Total Balance: ₹{finance.get('balance', 0):,.0f}\n"
            output += f"  This Month Expenses: ₹{finance.get('month_expense', 0):,.0f}\n"
            output += f"  This Month Income: ₹{finance.get('month_income', 0):,.0f}\n"
            
            top_categories = finance.get('top_categories', [])
            if top_categories:
                output += "\n  Top Spending:\n"
                for cat, amt in top_categories[:3]:
                    output += f"    • {cat}: ₹{amt:,.0f}\n"
        output += "\n"
        
        # Journal Section
        journal = report_data.get('journal', {})
        output += "📔 **JOURNAL**\n"
        output += "-" * 30 + "\n"
        output += f"  Total Entries: {journal.get('total', 0)}\n"
        output += f"  This Month: {journal.get('this_month', 0)}\n"
        
        top_tags = journal.get('top_tags', [])
        if top_tags:
            tags_str = ", ".join([f"#{t}" for t, _ in top_tags[:5]])
            output += f"  Popular Tags: {tags_str}\n"
        output += "\n"
        
        # Habits Section
        habits = report_data.get('habits', {})
        output += "✅ **HABITS**\n"
        output += "-" * 30 + "\n"
        output += f"  Active Habits: {habits.get('total', 0)}\n"
        output += f"  Completed Today: {habits.get('completed_today', 0)}\n"
        
        streaks = habits.get('streaks', [])
        if streaks:
            output += "  Best Streaks:\n"
            for name, streak in streaks[:3]:
                output += f"    • {name}: {streak} days 🔥\n"
        output += "\n"
        
        # Summary
        output += "=" * 50 + "\n"
        positive = random.choice(self.hindi_phrases['positive'])
        output += f"\n{positive} Keep it up! 💪\n"
        
        return output
    
    def format_ask_response(self, query: str, context: str, answer: str) -> str:
        """Format ask command response
        
        Args:
            query: User's question
            context: Retrieved context (for debugging/transparency)
            answer: Generated answer
        
        Returns:
            Formatted response
        """
        output = self._random_template('ask_intro')
        
        if not answer or answer.strip() == "":
            return self._random_template('ask_no_result')
        
        output += answer
        
        # Add follow-up suggestion
        output += "\n\n💡 More info? Try: search <keyword>"
        
        return output
    
    def format_reasoning_response(self, trace, answer: str) -> str:
        """Format response with reasoning trace
        
        Args:
            trace: ReasoningTrace object with steps, pros/cons, safety checks
            answer: Generated answer
        
        Returns:
            Formatted response with reasoning visible
        """
        output = ""
        
        # Show reasoning header
        output += "🤔 **Soch raha hoon...**\n"
        output += "-" * 40 + "\n\n"
        
        # Show reasoning steps
        for step in trace.steps:
            output += f"  {step.step_num}. {step.description}\n"
            output += f"     → {step.result}\n"
        output += "\n"
        
        # Show pros/cons if available
        if trace.pros_cons:
            pc = trace.pros_cons
            if pc.pros or pc.cons:
                output += "⚖️ **Analysis:**\n"
                for pro in pc.pros:
                    output += f"  ✓ {pro}\n"
                for con in pc.cons:
                    output += f"  ✗ {con}\n"
                output += "\n"
        
        # Show safety warnings
        if trace.has_warnings():
            output += "⚠️ **Warning:**\n"
            for check in trace.safety_checks:
                if not check.passed:
                    output += f"  {check.warning}\n"
            output += "\n"
        
        # Separator
        output += "-" * 40 + "\n"
        
        # Decision badge
        decision_badges = {
            'appears_affordable': '✅ Looks OK',
            'reconsider': '⚠️ Think Again',
            'neutral': '🤔 Your Call',
            'provide_info': 'ℹ️ Info',
            'plan_generated': '📋 Plan Ready',
            'habit_advice': '💪 Keep Going',
            'general_response': '💬 Answer'
        }
        badge = decision_badges.get(trace.decision, '💬')
        output += f"\n{badge}\n\n"
        
        # The answer
        output += "💡 **Answer:**\n"
        output += answer + "\n"
        
        # Hinglish encouragement based on outcome
        if trace.decision == 'reconsider':
            encourage = random.choice([
                "Bhai, thoda soch lo pehle!",
                "Arre, balance check karo once.",
                "Patience rakho, time aayega!"
            ])
        elif trace.decision == 'appears_affordable':
            encourage = random.choice([
                "Looks good bhai! 👍",
                "Theek lag raha hai!",
                "All clear! Go for it!"
            ])
        else:
            encourage = random.choice(self.hindi_phrases['positive'])
        
        output += f"\n{encourage}\n"
        
        return output
    
    def format_success(self, action: str) -> str:
        """Format success message"""
        return self._random_template('success', action=action)
    
    def format_error(self, error: str) -> str:
        """Format error message"""
        return self._random_template('error', error=error)
    
    def get_greeting(self) -> str:
        """Get a friendly greeting"""
        greet = random.choice(self.hindi_phrases['greeting'])
        time_greet = self._time_greeting()
        return f"{greet} {time_greet}"
    
    def get_farewell(self) -> str:
        """Get a friendly farewell"""
        return random.choice(self.hindi_phrases['farewell'])
    
    def get_encouragement(self) -> str:
        """Get encouraging message"""
        return random.choice(self.hindi_phrases['encourage'])


# Singleton instance
_persona_instance = None

def get_persona() -> PersonaGenerator:
    """Get the global persona instance"""
    global _persona_instance
    if _persona_instance is None:
        _persona_instance = PersonaGenerator()
    return _persona_instance
