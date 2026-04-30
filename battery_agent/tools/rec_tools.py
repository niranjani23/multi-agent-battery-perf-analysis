"""
Recommendation tool: validate and structure the LLM-generated recommendations.

The LLM constructs the recommendations grounded in analysis evidence,
then calls this tool to lock them into a validated schema.
"""

from . import analysis_tools

_results: dict = {}

REQUIRED_REC_FIELDS = {"action", "reasoning", "expected_benefit", "tradeoff"}


def generate_recommendations(
    recommendations: list,
    gap_drivers: dict | None = None,
    dispatch_comparison: dict | None = None,
    soc_analysis: dict | None = None,
) -> dict:
    """
    Validate and store exactly 2 structured recommendations.

    Each recommendation must contain: action, reasoning, expected_benefit, tradeoff.
    The tool checks that recommendations reference actual evidence from the analysis.
    """
    # Fall back to cached results if not provided
    gd = gap_drivers or analysis_tools._results.get("gap_drivers", {})
    dc = dispatch_comparison or analysis_tools._results.get("dispatch_comparison", {})
    sa = soc_analysis or analysis_tools._results.get("soc_analysis", {})

    if not isinstance(recommendations, list):
        return {"status": "error", "message": "recommendations must be a list."}

    if len(recommendations) != 2:
        return {
            "status": "error",
            "message": f"Exactly 2 recommendations required. Got {len(recommendations)}.",
        }

    validated = []
    for i, rec in enumerate(recommendations):
        missing = REQUIRED_REC_FIELDS - set(rec.keys())
        if missing:
            return {
                "status": "error",
                "message": f"Recommendation {i+1} missing fields: {sorted(missing)}",
            }
        # Check that reasoning contains some reference to evidence keywords
        reasoning_lower = str(rec.get("reasoning", "")).lower()
        evidence_keywords = ["dispatch", "soc", "price", "charge", "discharge", "revenue", "gap", "interval"]
        if not any(kw in reasoning_lower for kw in evidence_keywords):
            return {
                "status": "error",
                "message": (
                    f"Recommendation {i+1} reasoning does not reference any analysis evidence. "
                    "Reasoning must be grounded in dispatch, SOC, price, or revenue findings."
                ),
            }
        validated.append({
            "id": i + 1,
            "action": str(rec["action"]),
            "reasoning": str(rec["reasoning"]),
            "expected_benefit": str(rec["expected_benefit"]),
            "tradeoff": str(rec["tradeoff"]),
        })

    result = {
        "status": "ok",
        "recommendations": validated,
        "supporting_evidence": {
            "primary_driver": gd.get("primary_driver"),
            "secondary_driver": gd.get("secondary_driver"),
            "gap_dollars": gd.get("total_gap_dollars"),
            "missed_discharge_intervals": dc.get("missed_discharge_intervals"),
            "soc_constrained_intervals": sa.get("soc_constrained_discharge_intervals"),
        },
    }
    _results["recommendations"] = result
    return result


# ---------------------------------------------------------------------------
# Claude tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "generate_recommendations",
        "description": (
            "Validate and store exactly 2 actionable recommendations grounded in the analysis evidence. "
            "Each recommendation must include: action, reasoning (tied to specific evidence), "
            "expected_benefit, and tradeoff. "
            "Pass gap_drivers, dispatch_comparison, and soc_analysis from the analysis agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "description": "Array of exactly 2 recommendation objects.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "The specific action to take."},
                            "reasoning": {
                                "type": "string",
                                "description": "Evidence-grounded explanation from analysis tool outputs.",
                            },
                            "expected_benefit": {
                                "type": "string",
                                "description": "Quantified or qualified expected improvement.",
                            },
                            "tradeoff": {
                                "type": "string",
                                "description": "One key tradeoff or risk of this action.",
                            },
                        },
                        "required": ["action", "reasoning", "expected_benefit", "tradeoff"],
                    },
                    "minItems": 2,
                    "maxItems": 2,
                },
                "gap_drivers": {
                    "type": "object",
                    "description": "Output from find_gap_drivers.",
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
            "required": ["recommendations"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> dict:
    if name == "generate_recommendations":
        return generate_recommendations(
            recommendations=inputs.get("recommendations", []),
            gap_drivers=inputs.get("gap_drivers"),
            dispatch_comparison=inputs.get("dispatch_comparison"),
            soc_analysis=inputs.get("soc_analysis"),
        )
    else:
        return {"status": "error", "message": f"Unknown tool: {name}"}
