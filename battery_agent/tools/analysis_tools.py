"""
Analysis tools: revenue summary, high-price intervals, dispatch comparison,
SOC analysis, and gap-driver synthesis.

All tools read the cleaned DataFrame from data_tools._state.
The LLM never receives raw rows — only JSON summaries.
"""

import json
import numpy as np
import pandas as pd
from . import data_tools

# Module-level cache for intermediate results (used as fallback by find_gap_drivers)
_results: dict = {}


def _get_clean_df() -> pd.DataFrame | None:
    return data_tools._state.get("clean_df")


def _df_error(fn_name: str) -> dict:
    return {
        "status": "error",
        "message": f"No clean data available for {fn_name}. Run the data prep agent first.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _round(val, decimals: int = 4):
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return val


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def compute_revenue_summary() -> dict:
    df = _get_clean_df()
    if df is None:
        return _df_error("compute_revenue_summary")

    try:
        by_combo = {}
        for combo, sub in df.groupby("COMBO"):
            by_combo[combo] = {
                "total_revenue": _round(sub["REVENUE"].sum()),
                "avg_price": _round(sub["PRICE_ENERGY"].mean()),
                "total_charge_MWh": _round(sub["CHARGE_ENERGY"].sum()),
                "total_discharge_MWh": _round(sub["DISCHARGE_ENERGY"].sum()),
                "intervals": int(len(sub)),
            }

        # Primary comparison: historical/cleared vs perfect/cleared
        hist = by_combo.get("historical/cleared", {})
        perf = by_combo.get("perfect/cleared", {})

        hist_rev = hist.get("total_revenue") or 0.0
        perf_rev = perf.get("total_revenue") or 0.0
        gap = _round(perf_rev - hist_rev)
        gap_pct = _round((gap / perf_rev * 100) if perf_rev else None)

        result = {
            "status": "ok",
            "by_combo": by_combo,
            "historical_cleared_total_revenue": _round(hist_rev),
            "perfect_cleared_total_revenue": _round(perf_rev),
            "gap_dollars": gap,
            "gap_pct": gap_pct,
            "combos_available": list(by_combo.keys()),
        }
        _results["revenue_summary"] = result
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def identify_high_price_intervals(threshold: float | None = None) -> dict:
    df = _get_clean_df()
    if df is None:
        return _df_error("identify_high_price_intervals")

    try:
        # Default threshold: 75th percentile of price across all rows
        if threshold is None:
            threshold = float(df["PRICE_ENERGY"].quantile(0.75))

        high_mask = df["PRICE_ENERGY"] >= threshold

        high_df = df[high_mask].copy()
        n_high = int(high_mask.sum())

        def combo_stats(scenario: str, schedule: str) -> dict:
            sub = high_df[(high_df["SCENARIO_NAME"] == scenario) & (high_df["SCHEDULE_TYPE"] == schedule)]
            return {
                "intervals": int(len(sub)),
                "total_charge_MWh": _round(sub["CHARGE_ENERGY"].sum()),
                "total_discharge_MWh": _round(sub["DISCHARGE_ENERGY"].sum()),
                "total_revenue": _round(sub["REVENUE"].sum()),
            }

        hist_stats = combo_stats("historical", "cleared")
        perf_stats = combo_stats("perfect", "cleared")

        missed_rev = _round(
            (perf_stats["total_revenue"] or 0) - (hist_stats["total_revenue"] or 0)
        )

        # Top missed intervals: where perfect earned most but historical earned least
        hist_hp = high_df[
            (high_df["SCENARIO_NAME"] == "historical") & (high_df["SCHEDULE_TYPE"] == "cleared")
        ][["START_DATETIME", "PRICE_ENERGY", "DISCHARGE_ENERGY", "REVENUE"]].copy()

        perf_hp = high_df[
            (high_df["SCENARIO_NAME"] == "perfect") & (high_df["SCHEDULE_TYPE"] == "cleared")
        ][["START_DATETIME", "PRICE_ENERGY", "DISCHARGE_ENERGY", "REVENUE"]].copy()

        top_missed = []
        if not perf_hp.empty and not hist_hp.empty:
            merged = perf_hp.merge(
                hist_hp, on="START_DATETIME", suffixes=("_perfect", "_hist")
            )
            merged["rev_diff"] = merged["REVENUE_perfect"] - merged["REVENUE_hist"]
            top5 = merged.nlargest(5, "rev_diff")
            for _, row in top5.iterrows():
                top_missed.append({
                    "datetime": str(row["START_DATETIME"]),
                    "price": _round(row["PRICE_ENERGY_perfect"]),
                    "perfect_discharge_MWh": _round(row["DISCHARGE_ENERGY_perfect"]),
                    "hist_discharge_MWh": _round(row["DISCHARGE_ENERGY_hist"]),
                    "revenue_diff": _round(row["rev_diff"]),
                })

        result = {
            "status": "ok",
            "threshold_used": _round(threshold),
            "high_price_intervals_count": n_high,
            "historical_cleared_in_high_price": hist_stats,
            "perfect_cleared_in_high_price": perf_stats,
            "missed_revenue_in_high_price": missed_rev,
            "top_5_missed_intervals": top_missed,
        }
        _results["high_price_analysis"] = result
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def compare_dispatch() -> dict:
    df = _get_clean_df()
    if df is None:
        return _df_error("compare_dispatch")

    try:
        hist = df[(df["SCENARIO_NAME"] == "historical") & (df["SCHEDULE_TYPE"] == "cleared")].copy()
        perf = df[(df["SCENARIO_NAME"] == "perfect") & (df["SCHEDULE_TYPE"] == "cleared")].copy()

        if hist.empty or perf.empty:
            return {"status": "error", "message": "Missing historical/cleared or perfect/cleared data."}

        merged = hist[["START_DATETIME", "CHARGE_ENERGY", "DISCHARGE_ENERGY", "REVENUE"]].merge(
            perf[["START_DATETIME", "CHARGE_ENERGY", "DISCHARGE_ENERGY", "REVENUE"]],
            on="START_DATETIME",
            suffixes=("_hist", "_perf"),
        )

        eps = 1e-6  # threshold for "non-zero" energy

        # Unnecessary charges: historical charged when perfect did not
        unnecessary_charge_mask = (merged["CHARGE_ENERGY_hist"] > eps) & (merged["CHARGE_ENERGY_perf"] <= eps)
        # Missed discharges: perfect discharged when historical did not
        missed_discharge_mask = (merged["DISCHARGE_ENERGY_perf"] > eps) & (merged["DISCHARGE_ENERGY_hist"] <= eps)
        # Both charged (different amounts)
        both_charged_mask = (merged["CHARGE_ENERGY_hist"] > eps) & (merged["CHARGE_ENERGY_perf"] > eps)
        # Both discharged (different amounts)
        both_discharged_mask = (merged["DISCHARGE_ENERGY_hist"] > eps) & (merged["DISCHARGE_ENERGY_perf"] > eps)

        result = {
            "status": "ok",
            "intervals_compared": int(len(merged)),
            # Totals
            "total_charge_hist_MWh": _round(hist["CHARGE_ENERGY"].sum()),
            "total_discharge_hist_MWh": _round(hist["DISCHARGE_ENERGY"].sum()),
            "total_charge_perf_MWh": _round(perf["CHARGE_ENERGY"].sum()),
            "total_discharge_perf_MWh": _round(perf["DISCHARGE_ENERGY"].sum()),
            # Diffs
            "charge_diff_MWh": _round(perf["CHARGE_ENERGY"].sum() - hist["CHARGE_ENERGY"].sum()),
            "discharge_diff_MWh": _round(perf["DISCHARGE_ENERGY"].sum() - hist["DISCHARGE_ENERGY"].sum()),
            # Event counts
            "unnecessary_charge_intervals": int(unnecessary_charge_mask.sum()),
            "missed_discharge_intervals": int(missed_discharge_mask.sum()),
            "both_charged_intervals": int(both_charged_mask.sum()),
            "both_discharged_intervals": int(both_discharged_mask.sum()),
            # Energy in missed/unnecessary events
            "unnecessary_charge_MWh": _round(merged.loc[unnecessary_charge_mask, "CHARGE_ENERGY_hist"].sum()),
            "missed_discharge_MWh": _round(merged.loc[missed_discharge_mask, "DISCHARGE_ENERGY_perf"].sum()),
            "missed_discharge_revenue": _round(merged.loc[missed_discharge_mask, "REVENUE_perf"].sum()),
        }
        _results["dispatch_comparison"] = result
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def analyze_soc() -> dict:
    df = _get_clean_df()
    if df is None:
        return _df_error("analyze_soc")

    try:
        hist = df[(df["SCENARIO_NAME"] == "historical") & (df["SCHEDULE_TYPE"] == "cleared")].sort_values("START_DATETIME")
        perf = df[(df["SCENARIO_NAME"] == "perfect") & (df["SCHEDULE_TYPE"] == "cleared")].sort_values("START_DATETIME")

        if hist.empty or perf.empty:
            return {"status": "error", "message": "Missing historical/cleared or perfect/cleared data."}

        # High-price threshold (75th percentile)
        threshold = float(df["PRICE_ENERGY"].quantile(0.75))
        hist_high = hist[hist["PRICE_ENERGY"] >= threshold]
        perf_high = perf[perf["PRICE_ENERGY"] >= threshold]

        # SOC near-zero: can't discharge (SOC < 5% is effectively depleted)
        low_soc_threshold = 5.0
        hist_low_soc = hist[hist["SOC"] < low_soc_threshold]

        # Merge to find intervals where historical SOC was low but perfect discharged
        perf_discharged = perf[perf["DISCHARGE_ENERGY"] > 1e-6][["START_DATETIME", "DISCHARGE_ENERGY", "PRICE_ENERGY"]].copy()
        hist_soc_ts = hist[["START_DATETIME", "SOC", "DISCHARGE_ENERGY"]].copy()

        merged_soc = hist_soc_ts.merge(perf_discharged, on="START_DATETIME", suffixes=("_hist", "_perf"))
        soc_blocked = merged_soc[
            (merged_soc["SOC"] < low_soc_threshold) & (merged_soc["DISCHARGE_ENERGY_hist"] <= 1e-6)
        ]

        result = {
            "status": "ok",
            "historical_cleared_soc": {
                "min": _round(hist["SOC"].min()),
                "max": _round(hist["SOC"].max()),
                "mean": _round(hist["SOC"].mean()),
                "pct_time_below_20": _round(((hist["SOC"] < 20).sum() / len(hist) * 100) if len(hist) else None),
                "pct_time_above_80": _round(((hist["SOC"] > 80).sum() / len(hist) * 100) if len(hist) else None),
            },
            "perfect_cleared_soc": {
                "min": _round(perf["SOC"].min()),
                "max": _round(perf["SOC"].max()),
                "mean": _round(perf["SOC"].mean()),
                "pct_time_below_20": _round(((perf["SOC"] < 20).sum() / len(perf) * 100) if len(perf) else None),
                "pct_time_above_80": _round(((perf["SOC"] > 80).sum() / len(perf) * 100) if len(perf) else None),
            },
            "soc_constrained_discharge_intervals": int(len(soc_blocked)),
            "avg_soc_hist_at_high_price": _round(hist_high["SOC"].mean()) if not hist_high.empty else None,
            "avg_soc_perf_at_high_price": _round(perf_high["SOC"].mean()) if not perf_high.empty else None,
            "low_soc_threshold_pct": low_soc_threshold,
            "high_price_threshold": _round(threshold),
        }
        _results["soc_analysis"] = result
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def find_gap_drivers(
    revenue_summary: dict | None = None,
    high_price_analysis: dict | None = None,
    dispatch_comparison: dict | None = None,
    soc_analysis: dict | None = None,
) -> dict:
    """
    Synthesise evidence from prior tools into primary and secondary gap drivers.
    Falls back to module-level cached results if arguments are None or empty.
    """
    rs = revenue_summary or _results.get("revenue_summary", {})
    hp = high_price_analysis or _results.get("high_price_analysis", {})
    dc = dispatch_comparison or _results.get("dispatch_comparison", {})
    sa = soc_analysis or _results.get("soc_analysis", {})

    missing = [name for name, val in [("revenue_summary", rs), ("high_price_analysis", hp),
                                       ("dispatch_comparison", dc), ("soc_analysis", sa)] if not val]
    if missing:
        return {
            "status": "error",
            "message": f"Missing required inputs: {missing}. Run all analysis tools first.",
        }

    try:
        gap = rs.get("gap_dollars", 0) or 0
        gap_pct = rs.get("gap_pct", 0) or 0
        missed_hp_rev = hp.get("missed_revenue_in_high_price", 0) or 0
        missed_dis_rev = dc.get("missed_discharge_revenue", 0) or 0
        soc_constrained = sa.get("soc_constrained_discharge_intervals", 0) or 0
        unnecessary = dc.get("unnecessary_charge_intervals", 0) or 0
        missed_intervals = dc.get("missed_discharge_intervals", 0) or 0
        hist_hp_dis = (hp.get("historical_cleared_in_high_price") or {}).get("total_discharge_MWh", 0) or 0
        perf_hp_dis = (hp.get("perfect_cleared_in_high_price") or {}).get("total_discharge_MWh", 0) or 0
        hist_soc_mean = (sa.get("historical_cleared_soc") or {}).get("mean")
        perf_soc_mean = (sa.get("perfect_cleared_soc") or {}).get("mean")

        # Determine primary driver heuristically
        hp_fraction = abs(missed_hp_rev / gap) if gap else 0

        if hp_fraction > 0.5:
            primary_factor = "missed_discharge_during_high_price_periods"
            primary_evidence = (
                f"Historical dispatched {hist_hp_dis:.2f} MWh vs perfect's {perf_hp_dis:.2f} MWh "
                f"during {hp.get('high_price_intervals_count', '?')} high-price intervals "
                f"(price >= ${hp.get('threshold_used', '?'):.2f}/MWh), "
                f"leaving ${missed_hp_rev:.2f} unrealised."
            )
            primary_impact = _round(missed_hp_rev)
        else:
            primary_factor = "suboptimal_dispatch_timing"
            primary_evidence = (
                f"{missed_intervals} intervals where perfect discharged but historical did not, "
                f"representing ${missed_dis_rev:.2f} in missed revenue."
            )
            primary_impact = _round(missed_dis_rev)

        # Secondary driver
        if soc_constrained > 0:
            secondary_factor = "soc_constraints_blocking_discharge"
            secondary_evidence = (
                f"SOC fell below {sa.get('low_soc_threshold_pct', 5)}% in {soc_constrained} intervals "
                f"where perfect foresight would have discharged. "
                f"Average SOC during high-price periods: historical {hist_soc_mean:.1f}% vs "
                f"perfect {perf_soc_mean:.1f}%."
            ) if (hist_soc_mean is not None and perf_soc_mean is not None) else (
                f"SOC constraints blocked discharge in {soc_constrained} intervals."
            )
        else:
            secondary_factor = "unnecessary_charging_during_low_price_periods"
            secondary_evidence = (
                f"{unnecessary} intervals where historical charged but perfect foresight did not, "
                f"potentially consuming capacity needed for later discharge."
            )

        result = {
            "status": "ok",
            "total_gap_dollars": _round(gap),
            "total_gap_pct": _round(gap_pct),
            "primary_driver": {
                "factor": primary_factor,
                "evidence": primary_evidence,
                "revenue_impact_dollars": primary_impact,
            },
            "secondary_driver": {
                "factor": secondary_factor,
                "evidence": secondary_evidence,
            },
            "summary": (
                f"The ${gap:.2f} performance gap ({gap_pct:.1f}%) is primarily driven by "
                f"{primary_factor.replace('_', ' ')}, with {secondary_factor.replace('_', ' ')} "
                f"as a contributing factor."
            ),
        }
        _results["gap_drivers"] = result
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Claude tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "compute_revenue_summary",
        "description": (
            "Compute total revenue for each scenario/schedule combination. "
            "Returns the revenue gap ($) between historical/cleared and perfect/cleared. "
            "Call after the data prep agent has loaded and cleaned the CSV."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "identify_high_price_intervals",
        "description": (
            "Find intervals where PRICE_ENERGY is above a threshold (default: 75th percentile). "
            "Compares historical vs perfect dispatch and revenue in those windows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Price threshold ($/MWh). Omit to use 75th percentile.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "compare_dispatch",
        "description": (
            "Compare CHARGE_ENERGY and DISCHARGE_ENERGY between historical/cleared and "
            "perfect/cleared scenarios. Identifies missed discharge intervals and unnecessary charges."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "analyze_soc",
        "description": (
            "Analyse State of Charge (SOC) profiles for historical vs perfect scenarios. "
            "Identifies intervals where low SOC prevented discharge during high-price periods."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "find_gap_drivers",
        "description": (
            "Synthesise all prior analysis outputs to identify the primary and secondary drivers "
            "of the performance gap. Pass the outputs from all four preceding tools as inputs. "
            "Must be called last, after compute_revenue_summary, identify_high_price_intervals, "
            "compare_dispatch, and analyze_soc have all been called."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "revenue_summary": {
                    "type": "object",
                    "description": "Output from compute_revenue_summary.",
                },
                "high_price_analysis": {
                    "type": "object",
                    "description": "Output from identify_high_price_intervals.",
                },
                "dispatch_comparison": {
                    "type": "object",
                    "description": "Output from compare_dispatch.",
                },
                "soc_analysis": {
                    "type": "object",
                    "description": "Output from analyze_soc.",
                },
            },
            "required": ["revenue_summary", "high_price_analysis", "dispatch_comparison", "soc_analysis"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> dict:
    """Dispatch an analysis tool call by name."""
    if name == "compute_revenue_summary":
        return compute_revenue_summary()
    elif name == "identify_high_price_intervals":
        return identify_high_price_intervals(threshold=inputs.get("threshold"))
    elif name == "compare_dispatch":
        return compare_dispatch()
    elif name == "analyze_soc":
        return analyze_soc()
    elif name == "find_gap_drivers":
        return find_gap_drivers(
            revenue_summary=inputs.get("revenue_summary"),
            high_price_analysis=inputs.get("high_price_analysis"),
            dispatch_comparison=inputs.get("dispatch_comparison"),
            soc_analysis=inputs.get("soc_analysis"),
        )
    else:
        return {"status": "error", "message": f"Unknown tool: {name}"}
