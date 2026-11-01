"""
Orchestrator

Coordinates the three sub-agents in sequence:
  Data Prep → Analysis → Recommendations → PDF

The orchestrator never touches raw CSV rows directly.
All data access goes through the tools layer.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic
from dotenv import load_dotenv

from .agents import data_prep, analysis, recommendations
from .tools import data_tools, analysis_tools, rec_tools
from .report import pdf_generator

load_dotenv()


def _make_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to your environment or a .env file in the project root."
        )
    return anthropic.Anthropic(api_key=api_key)


def run_analysis(
    file_path: str,
    user_query: str = "Analyze the battery performance data and provide recommendations.",
    log_callback: Callable[[str], None] | None = None,
) -> dict:
    """
    Run the full analysis pipeline and return a report dict with PDF bytes.

    Args:
        file_path:     Path to the battery performance CSV.
        user_query:    Optional user question to frame the analysis.
        log_callback:  Called with progress messages (str) as the pipeline runs.

    Returns:
        {
            "status": "ok" | "error",
            "message": str,          # error description if status=="error"
            "metadata": {...},
            "data_manifest": str,    # Data prep agent output
            "analysis": str,         # Analysis agent output
            "revenue_summary": dict,
            "gap_drivers": dict,
            "dispatch_comparison": dict,
            "soc_analysis": dict,
            "recommendations": dict,
            "pdf_bytes": bytes,
        }
    """
    def _log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------
    if not Path(file_path).exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    try:
        client = _make_client()
    except EnvironmentError as exc:
        return {"status": "error", "message": str(exc)}

    run_start = datetime.now()
    _log(f"[orchestrator] analysis started at {run_start.isoformat(timespec='seconds')}")
    _log(f"[orchestrator] file: {file_path}")
    _log(f"[orchestrator] query: {user_query}")

    # ------------------------------------------------------------------
    # Step 1: Data Prep Agent
    # ------------------------------------------------------------------
    _log("\n[orchestrator] === STEP 1: Data Prep Agent ===")
    try:
        data_manifest = data_prep.run(client=client, file_path=file_path, log_callback=_log)
    except Exception as exc:
        return {"status": "error", "message": f"Data prep agent failed: {exc}"}

    if not data_manifest:
        return {"status": "error", "message": "Data prep agent returned empty result."}

    _log(f"[orchestrator] data manifest received ({len(data_manifest)} chars)")

    # ------------------------------------------------------------------
    # Step 2: Analysis Agent
    # ------------------------------------------------------------------
    _log("\n[orchestrator] === STEP 2: Analysis Agent ===")
    try:
        analysis_summary = analysis.run(
            client=client, data_manifest=data_manifest, log_callback=_log
        )
    except Exception as exc:
        return {"status": "error", "message": f"Analysis agent failed: {exc}"}

    if not analysis_summary:
        return {"status": "error", "message": "Analysis agent returned empty result."}

    _log(f"[orchestrator] analysis summary received ({len(analysis_summary)} chars)")

    # ------------------------------------------------------------------
    # Step 3: Recommendation Agent
    # ------------------------------------------------------------------
    _log("\n[orchestrator] === STEP 3: Recommendation Agent ===")
    try:
        recs_result = recommendations.run(
            client=client, analysis_summary=analysis_summary, log_callback=_log
        )
    except Exception as exc:
        return {"status": "error", "message": f"Recommendation agent failed: {exc}"}

    _log(f"[orchestrator] recommendations received: status={recs_result.get('status', '?')}")

    # ------------------------------------------------------------------
    # Assemble final report dict
    # ------------------------------------------------------------------
    _log("\n[orchestrator] === Assembling Report ===")

    # Pull structured results from the tool caches
    revenue_summary = analysis_tools._results.get("revenue_summary", {})
    gap_drivers_result = analysis_tools._results.get("gap_drivers", {})
    dispatch_comparison = analysis_tools._results.get("dispatch_comparison", {})
    soc_analysis = analysis_tools._results.get("soc_analysis", {})

    # Derive battery ID and date from the file name / data
    clean_df = data_tools._state.get("clean_df")
    battery_id = "BLYTHB1"
    analysis_date = "Unknown"
    if clean_df is not None and "START_DATETIME" in clean_df.columns:
        dt_min = clean_df["START_DATETIME"].min()
        if hasattr(dt_min, "strftime"):
            analysis_date = dt_min.strftime("%Y-%m-%d")

    # Try to extract battery ID from the file path
    stem = Path(file_path).stem.upper()
    for part in stem.split("_"):
        if len(part) >= 5 and any(c.isdigit() for c in part):
            battery_id = part
            break

    report = {
        "status": "ok",
        "message": "Analysis complete.",
        "metadata": {
            "battery_id": battery_id,
            "analysis_date": analysis_date,
            "file_path": file_path,
            "user_query": user_query,
            "run_timestamp": run_start.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "data_manifest": data_manifest,
        "analysis": analysis_summary,
        "revenue_summary": revenue_summary,
        "gap_drivers": gap_drivers_result,
        "dispatch_comparison": dispatch_comparison,
        "soc_analysis": soc_analysis,
        "recommendations": recs_result,
    }

    # ------------------------------------------------------------------
    # Generate PDF
    # ------------------------------------------------------------------
    _log("[orchestrator] generating PDF...")
    try:
        pdf_bytes = pdf_generator.generate_pdf(report)
        report["pdf_bytes"] = pdf_bytes
        _log(f"[orchestrator] PDF generated ({len(pdf_bytes):,} bytes)")
    except Exception as exc:
        _log(f"[orchestrator] PDF generation failed: {exc}")
        report["pdf_bytes"] = None
        report["pdf_error"] = str(exc)

    elapsed = (datetime.now() - run_start).total_seconds()
    _log(f"\n[orchestrator] analysis complete in {elapsed:.1f}s")

    return report
