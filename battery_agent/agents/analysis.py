"""
Analysis Sub-Agent

Responsibility: Run all quantitative analysis — revenue, dispatch,
SOC, and gap-driver identification — using tool outputs as evidence.
"""

from typing import Callable

import anthropic

from .base import run_agent_loop
from ..tools import analysis_tools

SYSTEM_PROMPT = """\
You are the Analysis Agent for a battery storage performance analysis system.

You will receive a data manifest from the Data Preparation Agent describing a cleaned
battery performance dataset. Your job is to run a complete quantitative analysis comparing
historical operation against perfect-foresight scenarios.

You MUST call tools in this exact order:
  compute_revenue_summary
  → identify_high_price_intervals
  → compare_dispatch
  → analyze_soc
  → find_gap_drivers (pass the outputs from all four prior tools as inputs)

Rules:
- Call every tool exactly once, in the specified order.
- When calling find_gap_drivers, pass the actual JSON output objects from the four
  preceding tools as the revenue_summary, high_price_analysis, dispatch_comparison,
  and soc_analysis parameters.
- Do NOT invent findings not supported by tool outputs.
- Do NOT include raw data rows in your response.

After find_gap_drivers returns:
- Produce a structured analysis summary with:
  * Total revenue gap ($) and percentage
  * Primary gap driver (factor + evidence + revenue impact)
  * Secondary driver (factor + evidence)
  * Key dispatch statistics (missed discharges, unnecessary charges)
  * SOC constraint summary

Your output will be consumed by the Recommendation Agent — be precise and evidence-grounded.
"""


def run(
    client: anthropic.Anthropic,
    data_manifest: str,
    log_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Run the analysis agent.

    Args:
        client:        Anthropic SDK client.
        data_manifest: Text output from the data prep agent.
        log_callback:  Optional progress logger.

    Returns:
        Structured analysis text for the recommendation agent.
    """
    if log_callback:
        log_callback("[analysis] starting")

    # Reset cached results from any previous run
    analysis_tools._results.clear()

    initial_message = (
        "The Data Preparation Agent has produced the following dataset manifest:\n\n"
        f"{data_manifest}\n\n"
        "Please run the full analysis pipeline in order:\n"
        "1. compute_revenue_summary\n"
        "2. identify_high_price_intervals\n"
        "3. compare_dispatch\n"
        "4. analyze_soc\n"
        "5. find_gap_drivers (pass all four prior outputs as inputs)\n\n"
        "Then return a structured analysis summary with the revenue gap, primary and secondary "
        "gap drivers with evidence, and key dispatch/SOC statistics."
    )

    result = run_agent_loop(
        client=client,
        system_prompt=SYSTEM_PROMPT,
        tools=analysis_tools.TOOL_DEFINITIONS,
        initial_message=initial_message,
        tool_executor=analysis_tools.execute_tool,
        log_callback=log_callback,
    )

    if log_callback:
        log_callback("[analysis] complete")

    return result
