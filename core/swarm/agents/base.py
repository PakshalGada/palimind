"""Base Agent class for the Swarm architecture."""
from __future__ import annotations
import httpx
import json
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class AgentResult:
    message: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

class BaseAgent:
    """Base class for specialized swarm agents."""
    
    def __init__(self, name: str, system_prompt: str, ollama_url: str, model: str):
        self.name = name
        self.system_prompt = system_prompt
        self.ollama_url = ollama_url
        self.model = model
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: List[Dict[str, Any]] = []

    def register_tool(self, name: str, description: str, parameters: Dict[str, Any], func: Callable):
        """Register a tool that the agent can use."""
        self.tools[name] = func
        self.tool_schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        })

    def run(self, messages: List[Dict[str, Any]], stream: bool = False) -> AgentResult:
        """Run the agent on a conversation history."""
        sys_msg = [{"role": "system", "content": self.system_prompt}]
        full_messages = sys_msg + messages

        payload = {
            "model": self.model,
            "messages": full_messages,
            "stream": stream,
            "options": {"temperature": 0.0}
        }

        if self.tool_schemas:
            payload["tools"] = self.tool_schemas

        url = f"{self.ollama_url.rstrip('/')}/api/chat"
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                
                content = msg.get("content", "") or ""
                tool_calls = msg.get("tool_calls", []) or []
                
                return AgentResult(message=content, tool_calls=tool_calls)
        except Exception as e:
            return AgentResult(message=f"Error communicating with model: {e}")

    def execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute the tools requested by the LLM."""
        results = []
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name")
            args = tc.get("function", {}).get("arguments", {})
            # Some models return arguments as a JSON string
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_call_id = tc.get("id", func_name)
            if func_name in self.tools:
                try:
                    res = self.tools[func_name](**args)
                    results.append({
                        "role": "tool",
                        "content": str(res),
                        "name": func_name,
                        "tool_call_id": tool_call_id,
                    })
                except Exception as e:
                    results.append({
                        "role": "tool",
                        "content": f"Error: {e}",
                        "name": func_name,
                        "tool_call_id": tool_call_id,
                    })
            else:
                # Tool not registered — return a helpful error so the loop can continue
                results.append({
                    "role": "tool",
                    "content": f"Unknown tool: {func_name}",
                    "name": func_name or "unknown",
                    "tool_call_id": tool_call_id,
                })
        return results
