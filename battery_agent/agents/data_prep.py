"""
Data Prep Sub-Agent

Responsibility: Validate, clean, and summarize the raw CSV.
Fails fast on bad data before any LLM analysis tokens are spent.
"""

import json
from typing import Callable

import anthropic

from .base import run_agent_loop
from ..tools import data_tools

SYSTEM_PROMPT = """\
You are the Data Preparation Agent for a battery storage performance analysis system.

Your ONLY responsibilities are:
1. Load the CSV file and inspect its structure.
2. Validate the schema — check all required columns exist and flag any nulls.
3. Clean the data — normalize datetimes, coerce numeric columns, tag scenario/schedule combos.
4. Summarize the dataset shape — row counts, date range, combos, interval size.

You MUST call tools in this exact order:
  load_csv → validate_schema → clean_data → summarize_shape

If validate_schema returns errors (missing columns or critical nulls), stop immediately and
report the error clearly. Do NOT attempt clean_data on invalid data.

After all four tools have completed successfully, produce a brief structured summary of:
- Number of rows and date range
- Scenarios and schedule types found
- Interval size
- Any data quality warnings

Keep your final response concise — it will be consumed by the next agent, not a human reader.
Do not include raw data rows or CSV content in your response.
"""


def run(
    client: anthropic.Anthropic,
    file_path: str,
    log_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Run the data prep agent on the given CSV file path.
    Returns a text summary (clean data manifest) for the analysis agent.
    """
    if log_callback:
        log_callback("[data_prep] starting")

    # Reset module state before each run
    data_tools.reset_state()

    initial_message = (
        f"Please load and prepare the battery performance CSV at: {file_path}\n\n"
        "Run all four tools in order (load_csv → validate_schema → clean_data → summarize_shape) "
        "and return a structured summary of the dataset."
    )

    result = run_agent_loop(
        client=client,
        system_prompt=SYSTEM_PROMPT,
        tools=data_tools.TOOL_DEFINITIONS,
        initial_message=initial_message,
        tool_executor=data_tools.execute_tool,
        log_callback=log_callback,
    )

    if log_callback:
        log_callback("[data_prep] complete")

    return result
