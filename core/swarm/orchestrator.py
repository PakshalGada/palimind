from __future__ import annotations
import concurrent.futures
from typing import Dict, Any, List, Callable, Optional
from pathlib import Path

from core.hwfit.hardware import detect_hardware
from core.swarm.agents.email import EmailAgent
from core.swarm.agents.rag import RAGAgent
from core.swarm.agents.document import DocumentAgent
from core.swarm.agents.router import RouterAgent, keyword_route


class SwarmOrchestrator:
    """Orchestrates multiple agents and scales based on hardware constraints."""

    def __init__(self, root: Path, ollama_url: str, model: str):
        self.root = root
        self.ollama_url = ollama_url
        self.default_model = model

        # Hardware-aware scaling
        hw_profile = detect_hardware()
        best_vram_mb = max((g.vram_mb for g in hw_profile.gpus), default=0)

        if best_vram_mb >= 16000:
            self.max_workers = 4
        elif best_vram_mb >= 8000:
            self.max_workers = 2
        else:
            self.max_workers = 1  # CPU fallback or low VRAM

        print(f"[Swarm] Initialized with max_workers={self.max_workers} (VRAM: {best_vram_mb} MB)")

        self.agents: Dict[str, Any] = {
            "email": EmailAgent(ollama_url, self.default_model),
            "rag": RAGAgent(root, ollama_url, self.default_model),
            "document": DocumentAgent(root, ollama_url, self.default_model),
            "router": RouterAgent(ollama_url, self.default_model),
        }

        # Inject handoff tools into all agents
        for name, agent in self.agents.items():
            for target_name in self.agents:
                if target_name != name:
                    self._inject_transfer_tool(agent, target_name)

    def _inject_transfer_tool(self, agent, target_name: str):
        def transfer_func():
            return f"Transferred to {target_name}"

        agent.register_tool(
            name=f"transfer_to_{target_name}",
            description=f"Transfer the conversation to the {target_name} agent.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=transfer_func,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, progress_callback: Optional[Callable], text: str):
        """Send a progress update, if a callback is registered."""
        if progress_callback:
            progress_callback(text)

    def _route_via_llm(
        self,
        messages: list,
        current_agent,
        progress_callback: Optional[Callable],
        max_iterations: int = 10,
    ) -> str:
        """
        Run the ReAct loop starting from *current_agent*.
        Returns the final text answer.
        """
        for iteration in range(max_iterations):
            result = current_agent.run(messages)

            # ── No tool calls → agent produced a final answer ──────────
            if not result.tool_calls:
                msg = (result.message or "").strip()
                if msg:
                    return msg
                # Empty answer — try once more with an explicit nudge
                if iteration == 0:
                    messages.append({
                        "role": "user",
                        "content": "Please provide a detailed answer based on the information available.",
                    })
                    continue
                return "The agent returned an empty response. Try providing more details or asking a specific question."

            # Append the assistant turn (with tool calls)
            messages.append({
                "role": "assistant",
                "content": result.message or "",
                "tool_calls": result.tool_calls,
            })

            # ── Check for transfer tools ────────────────────────────────
            transfer_target: Optional[str] = None
            for tc in result.tool_calls:
                func_name = tc.get("function", {}).get("name", "")
                if func_name.startswith("transfer_to_"):
                    transfer_target = func_name.replace("transfer_to_", "")
                    break

            if transfer_target and transfer_target in self.agents:
                # Acknowledge the transfer in the message history
                ack_results = current_agent.execute_tools(
                    [tc for tc in result.tool_calls if tc.get("function", {}).get("name", "").startswith("transfer_to_")]
                )
                messages.extend(ack_results)
                current_agent = self.agents[transfer_target]
                print(f"[Swarm] Transferred to {current_agent.name}")
                self._emit(progress_callback, f"> *Transferred to **{current_agent.name}***\n\n")
                # Reset messages for the target agent to keep context clean
                # but preserve the original user query
                continue

            # ── Execute normal (non-transfer) tools ────────────────────
            if self.max_workers > 1 and len(result.tool_calls) > 1:
                tool_results: list = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = [
                        executor.submit(current_agent.execute_tools, [tc])
                        for tc in result.tool_calls
                    ]
                    for f in concurrent.futures.as_completed(futures):
                        tool_results.extend(f.result())
            else:
                tool_results = current_agent.execute_tools(result.tool_calls)

            messages.extend(tool_results)

        return "Agent reached maximum iterations without a final answer."

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_swarm(
        self,
        query: str,
        files: Optional[List[str]] = None,
        chat_mode: str = "llm",
        progress_callback: Optional[Callable] = None,
    ) -> str:
        """Run the swarm on a generic query."""

        # ── If specific files are attached, go straight to DocumentAgent ──
        if files:
            files_str = "\n- ".join(files)
            augmented_query = f"[User selected files:\n- {files_str}]\n\n{query}"
            target = "document"
            messages = [{"role": "user", "content": augmented_query}]
        elif chat_mode == "rag":
            target = "rag"
            messages = [{"role": "user", "content": query}]
        else:
            target = "router"
            messages = [{"role": "user", "content": query}]

        current_agent = self.agents[target]
        self._emit(progress_callback, f"> *Routing query to **{current_agent.name}**...*\n\n")
        print(f"[Swarm] Starting with agent: {current_agent.name}")

        # ── First pass through RouterAgent ────────────────────────────
        if target == "router":
            result = current_agent.run(messages)

            if result.tool_calls:
                # LLM chose a transfer — follow it
                transfer_target = None
                for tc in result.tool_calls:
                    func_name = tc.get("function", {}).get("name", "")
                    if func_name.startswith("transfer_to_"):
                        transfer_target = func_name.replace("transfer_to_", "")
                        break

                if transfer_target and transfer_target in self.agents:
                    ack = current_agent.execute_tools(result.tool_calls)
                    messages.append({
                        "role": "assistant",
                        "content": result.message or "",
                        "tool_calls": result.tool_calls,
                    })
                    messages.extend(ack)
                    current_agent = self.agents[transfer_target]
                    self._emit(progress_callback, f"> *Transferred to **{current_agent.name}***\n\n")
                    print(f"[Swarm] Routed to {current_agent.name}")
                else:
                    # Transfer target unknown — fall back to keyword routing
                    fallback = keyword_route(query)
                    if fallback and fallback in self.agents:
                        current_agent = self.agents[fallback]
                        self._emit(progress_callback, f"> *Keyword-routed to **{current_agent.name}***\n\n")
                        print(f"[Swarm] Keyword fallback → {current_agent.name}")

            elif not (result.message or "").strip():
                # Empty response from router → use keyword heuristics
                fallback = keyword_route(query)
                if fallback and fallback in self.agents:
                    current_agent = self.agents[fallback]
                    self._emit(progress_callback, f"> *Keyword-routed to **{current_agent.name}***\n\n")
                    print(f"[Swarm] Keyword fallback → {current_agent.name}")
                else:
                    # Router gave a direct answer
                    direct_answer = (result.message or "").strip()
                    if direct_answer:
                        return direct_answer

            else:
                # Router answered directly (simple greeting / general question)
                direct_answer = (result.message or "").strip()
                if direct_answer:
                    return direct_answer

                # Still nothing — try keyword fallback
                fallback = keyword_route(query)
                if fallback and fallback in self.agents:
                    current_agent = self.agents[fallback]
                    self._emit(progress_callback, f"> *Keyword-routed to **{current_agent.name}***\n\n")
                    print(f"[Swarm] Keyword fallback → {current_agent.name}")

        # ── Run the ReAct loop on the chosen agent ────────────────────
        return self._route_via_llm(messages, current_agent, progress_callback)

    def run_document_mode(self, file_path: str, query: str) -> str:
        """Directly run the DocumentAgent on a specific file."""
        agent = self.agents["document"]
        prompt = f"Analyse the file at '{file_path}'. User query: {query}"
        messages = [{"role": "user", "content": prompt}]

        result = agent.run(messages)
        if result.tool_calls:
            tool_results = agent.execute_tools(result.tool_calls)
            messages.append({
                "role": "assistant",
                "content": result.message or "",
                "tool_calls": result.tool_calls,
            })
            messages.extend(tool_results)
            result = agent.run(messages)

        msg = (result.message or "").strip()
        return msg if msg else "The agent returned an empty response. Try providing a specific query for this document."
