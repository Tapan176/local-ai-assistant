"""
Formatter - Converts structured tool outputs to human-readable text
"""
from typing import Dict, Any, Union, List

def format_tool_result(result: Union[str, Dict, List]) -> str:
    """Convert any tool result to a clean string"""
    if isinstance(result, str):
        return result
        
    if isinstance(result, dict):
        return _format_dict(result)
        
    if isinstance(result, list):
        return "\n".join([format_tool_result(item) for item in result])
        
    return str(result)

def _format_dict(data: Dict) -> str:
    """Format a dictionary into lines"""
    lines = []
    
    # Handle finance snapshot-like structures specifically
    if "accounts" in data and "balance" in data:
        lines.append(f"💰 Total Balance: ₹{data.get('balance', 0)}")
        if data.get("accounts"):
            lines.append("Accounts:")
            for acc in data['accounts']:
                lines.append(f"  - {acc.get('name')}: ₹{acc.get('balance')}")
        if data.get("recent_transactions"):
            lines.append("\nRecent Transactions:")
            for tx in data['recent_transactions'][:3]:
                lines.append(f"  • {tx.get('date', '')} {tx.get('category', '')}: ₹{tx.get('amount')}")
        return "\n".join(lines)
        
    # Generic dict formatting
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            v_str = format_tool_result(v)
            lines.append(f"{k.capitalize()}:\n{v_str}")
        else:
            lines.append(f"{k.capitalize()}: {v}")
            
    return "\n".join(lines)
