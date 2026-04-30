"""
Shared Claude tool_use agent loop.

Every sub-agent calls run_agent_loop() with its own system prompt,
tool definitions, initial message, and tool executor function.
"""

import json
import os
from typing import Callable

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
MAX_ITERATIONS = 20  # safety cap on tool-call rounds


def _extract_text(content: list) -> str:
    """Pull the first text block from the response content list."""
    for block in content:
        if hasattr(block, "type") and block.type == "text":
            return block.text
    return ""


def run_agent_loop(
    client: anthropic.Anthropic,
    system_prompt: str,
    tools: list[dict],
    initial_message: str,
    tool_executor: Callable[[str, dict], dict],
    log_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Run the standard tool_use agent loop until the model returns end_turn.

    Args:
        client:          Anthropic SDK client.
        system_prompt:   Agent-specific system prompt.
        tools:           List of Claude-format tool definitions.
        initial_message: The user-role message that starts the conversation.
        tool_executor:   Function(tool_name, tool_inputs) -> dict result.
        log_callback:    Optional callback for progress logging.

    Returns:
        Final text response from the model (the agent's conclusion).
    """
    def _log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    messages = [{"role": "user", "content": initial_message}]

    for iteration in range(MAX_ITERATIONS):
        _log(f"  [loop iter {iteration + 1}] calling model...")

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Append assistant message to conversation history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            _log("  [loop] end_turn reached.")
            return _extract_text(response.content)

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    _log(f"  [tool] calling {block.name}({json.dumps(block.input)[:120]}...)")
                    result = tool_executor(block.name, block.input)
                    _log(f"  [tool] {block.name} -> status={result.get('status', '?')}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason (e.g. max_tokens)
        _log(f"  [loop] unexpected stop_reason: {response.stop_reason}")
        return _extract_text(response.content)

    _log("[loop] reached max iterations — returning partial result.")
    return _extract_text(messages[-1]["content"]) if messages else ""
