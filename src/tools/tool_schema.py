"""Tool schema system for structured tool definitions (like Cursor/Copilot)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterSchema:
    """Schema for a tool parameter."""
    name: str
    type: str  # "string", "number", "integer", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None
    examples: list[Any] = field(default_factory=list)


@dataclass
class ToolSchema:
    """Complete schema for a tool (OpenAPI/JSON Schema compatible)."""
    name: str
    description: str
    parameters: list[ParameterSchema] = field(default_factory=list)
    returns: dict[str, Any] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    error_codes: dict[str, str] = field(default_factory=dict)

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            if param.examples:
                prop["examples"] = param.examples
            
            properties[param.name] = prop
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                    "enum": p.enum,
                    "examples": p.examples,
                }
                for p in self.parameters
            ],
            "returns": self.returns,
            "examples": self.examples,
            "error_codes": self.error_codes,
        }
