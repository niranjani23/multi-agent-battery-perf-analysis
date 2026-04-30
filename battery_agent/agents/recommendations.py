"""
Recommendation Sub-Agent

Responsibility: Produce exactly 2 actionable, evidence-grounded recommendations.
Cannot invent recommendations not supported by analysis tool outputs.
"""

from typing import Callable

import anthropic

from .base import run_agent_loop
from ..tools import rec_tools, analysis_tools

SYSTEM_PROMPT = """\
You are the Recommendation Agent for a battery storage performance analysis system.

You will receive a structured analysis summary from the Analysis Agent.
Your ONLY job is to produce exactly 2 actionable recommendations that would help the
battery operator close the performance gap between historical and perfect-foresight operation.

STRICT RULES:
1. You MUST produce exactly 2 recommendations — no more, no fewer.
2. Every recommendation MUST be grounded in specific evidence from the analysis.
   You MAY reference: dispatch statistics, SOC levels, price intervals, revenue gaps.
   You MUST NOT invent numbers, claim facts not in the analysis, or give generic advice.
3. Each recommendation must have all four fields:
   - action: The specific operational or strategic change to make.
   - reasoning: Explain WHY, citing specific evidence (numbers, intervals, percentages).
   - expected_benefit: What improvement is expected and roughly how much.
   - tradeoff: One key risk, cost, or constraint of this recommendation.
4. Call generate_recommendations once with both recommendations.
   If the tool returns an error (e.g., missing evidence reference), revise and retry.

Focus on recommendations that are:
- Specific and actionable (not "improve forecasting" — say HOW)
- Tied to the primary and secondary gap drivers identified in the analysis
- Realistic given battery operational constraints
"""


def run(
    client: anthropic.Anthropic,
    analysis_summary: str,
    log_callback: Callable[[str], None] | None = None,
) -> dict:
    """
    Run the recommendation agent.

    Args:
        client:           Anthropic SDK client.
        analysis_summary: Text output from the analysis agent.
        log_callback:     Optional progress logger.

    Returns:
        The validated recommendations dict from rec_tools, or an error dict.
    """
    if log_callback:
        log_callback("[recommendations] starting")

    # Clear any stale recommendation results
    rec_tools._results.clear()

    initial_message = (
        "The Analysis Agent has produced the following findings:\n\n"
        f"{analysis_summary}\n\n"
        "Based solely on this evidence, produce exactly 2 actionable recommendations "
        "to help the battery operator close the performance gap. "
        "Call generate_recommendations with both recommendations, the gap_drivers output, "
        "the dispatch_comparison output, and the soc_analysis output from the analysis."
    )

    text_result = run_agent_loop(
        client=client,
        system_prompt=SYSTEM_PROMPT,
        tools=rec_tools.TOOL_DEFINITIONS,
        initial_message=initial_message,
        tool_executor=rec_tools.execute_tool,
        log_callback=log_callback,
    )

    if log_callback:
        log_callback("[recommendations] complete")

    # Return the validated structured result if available, otherwise the text
    return rec_tools._results.get("recommendations") or {"status": "text_only", "text": text_result}
