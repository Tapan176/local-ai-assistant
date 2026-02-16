"""
Relative Date Parser - Human-like date understanding
Handles: next year, after N years, next month, on X feb next year
"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import re
from typing import Optional, Tuple


class RelativeDateParser:
    """
    Parse human-style relative dates
    
    Examples:
    - "next year" → today + 1 year
    - "after 2 years" → today + 2 years
    - "next month" → today + 1 month
    - "on 4 feb next year" → 2027-02-04
    - "tomorrow" → today + 1 day
    - "kal" (Hindi) → tomorrow
    """
    
    def __init__(self, reference_date: datetime = None):
        self.reference = reference_date or datetime.now()
    
    def parse(self, text: str) -> Tuple[datetime, bool]:
        """
        Parse relative date from text
        Returns: (parsed_datetime, was_parsed)
        """
        text_lower = text.lower().strip()
        
        # ===== NEXT YEAR =====
        # "next year" → +1 year
        if "next year" in text_lower:
            # Check for specific date like "on 4 feb next year"
            specific_match = re.search(
                r'(?:on\s+)?(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:next\s+year)',
                text_lower
            )
            if specific_match:
                day = int(specific_match.group(1))
                month_str = specific_match.group(2)
                month = self._month_to_num(month_str)
                year = self.reference.year + 1
                return datetime(year, month, day, 9, 0, 0), True
            
            # Just "next year" → same month/day next year
            next_year = self.reference.replace(year=self.reference.year + 1, hour=9, minute=0, second=0)
            return next_year, True
        
        # ===== AFTER N YEARS =====
        # "after 2 years", "in 3 years"
        years_match = re.search(r'(?:after|in)\s+(\d+)\s*years?', text_lower)
        if years_match:
            n_years = int(years_match.group(1))
            future = self.reference + relativedelta(years=n_years)
            return future.replace(hour=9, minute=0, second=0), True
        
        # ===== NEXT MONTH =====
        if "next month" in text_lower:
            next_month = self.reference + relativedelta(months=1)
            return next_month.replace(hour=9, minute=0, second=0), True
        
        # ===== AFTER N MONTHS =====
        months_match = re.search(r'(?:after|in)\s+(\d+)\s*months?', text_lower)
        if months_match:
            n_months = int(months_match.group(1))
            future = self.reference + relativedelta(months=n_months)
            return future.replace(hour=9, minute=0, second=0), True
        
        # ===== NEXT WEEK =====
        if "next week" in text_lower:
            next_week = self.reference + timedelta(weeks=1)
            return next_week.replace(hour=9, minute=0, second=0), True
        
        # ===== EXTRACT TIME FIRST (for combined patterns) =====
        # "at 8pm", "at 8:30 pm", "tomorrow at 5pm"
        time_match = re.search(r'(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)', text_lower)
        extracted_hour = None
        extracted_minute = 0
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            ampm = time_match.group(3)
            
            if ampm == 'pm' and hour != 12:
                hour += 12
            elif ampm == 'am' and hour == 12:
                hour = 0
            extracted_hour = hour
            extracted_minute = minute
        
        # ===== TOMORROW / KAL =====
        if "tomorrow" in text_lower or "kal" in text_lower:
            tomorrow = self.reference + timedelta(days=1)
            hour = extracted_hour if extracted_hour is not None else 9
            minute = extracted_minute if extracted_hour is not None else 0
            return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0), True
        
        # ===== DAY AFTER TOMORROW =====
        if "day after tomorrow" in text_lower or "parso" in text_lower:
            day_after = self.reference + timedelta(days=2)
            hour = extracted_hour if extracted_hour is not None else 9
            minute = extracted_minute if extracted_hour is not None else 0
            return day_after.replace(hour=hour, minute=minute, second=0, microsecond=0), True
        
        # ===== SPECIFIC TIME ONLY (no relative date) =====
        if extracted_hour is not None:
            # Default to tomorrow if time already passed today
            result = self.reference.replace(hour=extracted_hour, minute=extracted_minute, second=0, microsecond=0)
            if result <= self.reference:
                result = result + timedelta(days=1)
            return result, True
        
        # ===== SPECIFIC DATE (this year or next) =====
        # "on 4 feb", "march 10", "10 march"
        date_match = re.search(
            r'(?:on\s+)?(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+(\d{4}))?',
            text_lower
        )
        if not date_match:
            date_match = re.search(
                r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:\s+(\d{4}))?',
                text_lower
            )
            if date_match:
                month_str = date_match.group(1)
                day = int(date_match.group(2))
                year = int(date_match.group(3)) if date_match.group(3) else None
            else:
                date_match = None
        else:
            day = int(date_match.group(1))
            month_str = date_match.group(2)
            year = int(date_match.group(3)) if date_match.group(3) else None
        
        if date_match:
            month = self._month_to_num(month_str)
            if year is None:
                year = self.reference.year
                # If date already passed this year, use next year
                try:
                    test_date = datetime(year, month, day)
                    if test_date < self.reference:
                        year += 1
                except ValueError:
                    pass
            
            try:
                return datetime(year, month, day, 9, 0, 0), True
            except ValueError:
                pass
        
        # ===== NO MATCH =====
        return self.reference + timedelta(days=1), False
    
    def _month_to_num(self, month_str: str) -> int:
        """Convert month string to number"""
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        return months.get(month_str[:3].lower(), 1)
    
    def has_relative_date(self, text: str) -> bool:
        """Check if text contains relative date markers"""
        markers = [
            'next year', 'next month', 'next week',
            'after', 'in', 'years', 'months', 'weeks',
            'tomorrow', 'kal', 'parso',
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
            'am', 'pm'
        ]
        text_lower = text.lower()
        return any(m in text_lower for m in markers)


# Convenience function
def parse_relative_date(text: str, reference: datetime = None) -> datetime:
    """Parse relative date from text"""
    parser = RelativeDateParser(reference)
    result, _ = parser.parse(text)
    return result
