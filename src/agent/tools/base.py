"""
Tool Base - Abstract interface for all agent tools
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result from tool execution"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class BaseTool(ABC):
    """Abstract base class for all tools"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for LLM reference"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Description for LLM context"""
        pass
    
    @property
    @abstractmethod
    def actions(self) -> list:
        """List of available actions"""
        pass
    
    @abstractmethod
    def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
        """Execute the tool action"""
        pass
    
    def get_schema(self) -> Dict:
        """Get tool schema for LLM"""
        return {
            "name": self.name,
            "description": self.description,
            "actions": self.actions
        }
