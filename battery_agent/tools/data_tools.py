"""
Data preparation tools: load, validate, clean, summarize.

All tools operate on module-level state so the LLM never needs
to pass a DataFrame — only the file path is passed once.
"""

import json
import pandas as pd
from pathlib import Path

REQUIRED_COLUMNS = {
    "SCENARIO_NAME",
    "SCHEDULE_TYPE",
    "START_DATETIME",
    "SOC",
    "CHARGE_ENERGY",
    "DISCHARGE_ENERGY",
    "PRICE_ENERGY",
    "REVENUE",
}

# Module-level state shared across tool calls within a single analysis run
_state: dict = {
    "raw_df": None,
    "clean_df": None,
    "file_path": None,
}


def reset_state() -> None:
    """Clear all cached data (call before each new analysis run)."""
    _state["raw_df"] = None
    _state["clean_df"] = None
    _state["file_path"] = None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def load_csv(file_path: str) -> dict:
    """Load the CSV, store in module state, return shape + preview."""
    try:
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        df = pd.read_csv(file_path)

        # Try to parse the datetime column if present
        if "START_DATETIME" in df.columns:
            df["START_DATETIME"] = pd.to_datetime(df["START_DATETIME"], errors="coerce")

        _state["raw_df"] = df
        _state["file_path"] = file_path

        preview = df.head(5).copy()
        for col in preview.select_dtypes(include=["datetime64[ns, UTC]", "datetime64[ns]"]).columns:
            preview[col] = preview[col].astype(str)

        return {
            "status": "ok",
            "file_path": file_path,
            "shape": list(df.shape),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "preview": preview.to_dict(orient="records"),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def validate_schema() -> dict:
    """Validate required columns and data integrity on the loaded DataFrame."""
    df = _state["raw_df"]
    if df is None:
        return {"status": "error", "message": "No data loaded. Call load_csv first."}

    try:
        present = set(df.columns)
        missing = sorted(REQUIRED_COLUMNS - present)

        null_counts = {
            col: int(df[col].isna().sum())
            for col in REQUIRED_COLUMNS
            if col in df.columns
        }
        critical_nulls = {col: n for col, n in null_counts.items() if n > 0}

        scenarios = sorted(df["SCENARIO_NAME"].dropna().unique().tolist()) if "SCENARIO_NAME" in df.columns else []
        schedule_types = sorted(df["SCHEDULE_TYPE"].dropna().unique().tolist()) if "SCHEDULE_TYPE" in df.columns else []

        if missing:
            return {
                "status": "error",
                "message": f"Missing required columns: {missing}",
                "missing_columns": missing,
                "null_counts": null_counts,
            }

        return {
            "status": "ok",
            "missing_columns": [],
            "null_counts": null_counts,
            "critical_nulls": critical_nulls,
            "scenarios_found": scenarios,
            "schedule_types_found": schedule_types,
            "total_rows": len(df),
            "message": "Schema valid." if not critical_nulls else f"Schema valid but {len(critical_nulls)} columns have nulls.",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def clean_data() -> dict:
    """Normalize datetimes to UTC, drop unusable rows, store clean DataFrame."""
    df = _state["raw_df"]
    if df is None:
        return {"status": "error", "message": "No data loaded. Call load_csv first."}

    try:
        df = df.copy()

        # Ensure datetime parsed
        if not pd.api.types.is_datetime64_any_dtype(df["START_DATETIME"]):
            df["START_DATETIME"] = pd.to_datetime(df["START_DATETIME"], errors="coerce")

        # Localize to UTC if timezone-naive
        if df["START_DATETIME"].dt.tz is None:
            df["START_DATETIME"] = df["START_DATETIME"].dt.tz_localize("UTC")
        else:
            df["START_DATETIME"] = df["START_DATETIME"].dt.tz_convert("UTC")

        # Drop rows where the datetime couldn't be parsed
        n_before = len(df)
        df = df.dropna(subset=["START_DATETIME"])
        n_dropped = n_before - len(df)

        # Normalise string columns
        df["SCENARIO_NAME"] = df["SCENARIO_NAME"].str.strip().str.lower()
        df["SCHEDULE_TYPE"] = df["SCHEDULE_TYPE"].str.strip().str.lower()

        # Numeric coercion
        for col in ["SOC", "CHARGE_ENERGY", "DISCHARGE_ENERGY", "PRICE_ENERGY", "REVENUE"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Create combo key
        df["COMBO"] = df["SCENARIO_NAME"] + "/" + df["SCHEDULE_TYPE"]

        _state["clean_df"] = df

        combos = sorted(df["COMBO"].unique().tolist())
        dt_min = str(df["START_DATETIME"].min())
        dt_max = str(df["START_DATETIME"].max())

        return {
            "status": "ok",
            "rows_dropped": n_dropped,
            "rows_after_clean": len(df),
            "scenarios_found": sorted(df["SCENARIO_NAME"].unique().tolist()),
            "schedule_types_found": sorted(df["SCHEDULE_TYPE"].unique().tolist()),
            "combos_found": combos,
            "datetime_range": {"start": dt_min, "end": dt_max},
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def summarize_shape() -> dict:
    """Return row counts, date range, interval stats for each combo."""
    df = _state["clean_df"]
    if df is None:
        return {"status": "error", "message": "No clean data available. Call clean_data first."}

    try:
        combos = sorted(df["COMBO"].unique().tolist())
        intervals_per_combo = {}
        for combo in combos:
            sub = df[df["COMBO"] == combo]
            intervals_per_combo[combo] = int(len(sub))

        # Detect interval length in minutes
        for combo in combos:
            sub = df[df["COMBO"] == combo].sort_values("START_DATETIME")
            if len(sub) >= 2:
                delta = sub["START_DATETIME"].diff().dropna().mode()
                interval_minutes = int(delta.iloc[0].total_seconds() / 60) if len(delta) else None
                break
        else:
            interval_minutes = None

        return {
            "status": "ok",
            "total_rows": int(len(df)),
            "date_range": {
                "start": str(df["START_DATETIME"].min()),
                "end": str(df["START_DATETIME"].max()),
            },
            "scenarios": sorted(df["SCENARIO_NAME"].unique().tolist()),
            "schedule_types": sorted(df["SCHEDULE_TYPE"].unique().tolist()),
            "combos": combos,
            "interval_minutes": interval_minutes,
            "intervals_per_combo": intervals_per_combo,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Claude tool definitions (JSON schema for the API)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "load_csv",
        "description": (
            "Load the battery performance CSV from disk into memory. "
            "Returns the shape, column names, dtypes, and a 5-row preview. "
            "Must be called before any other data tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the CSV file.",
                }
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "validate_schema",
        "description": (
            "Validate that the loaded CSV has all required columns and check for nulls. "
            "Returns lists of missing columns and null counts. "
            "Call after load_csv."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "clean_data",
        "description": (
            "Normalize datetimes to UTC, coerce numeric columns, drop unparseable rows, "
            "and create a COMBO key (SCENARIO_NAME/SCHEDULE_TYPE). "
            "Stores the cleaned DataFrame for downstream tools. Call after validate_schema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "summarize_shape",
        "description": (
            "Return a summary of the clean dataset: total rows, date range, "
            "scenario/schedule combos found, interval size, and row count per combo. "
            "Call after clean_data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> dict:
    """Dispatch a tool call by name. Returns a JSON-serialisable dict."""
    if name == "load_csv":
        return load_csv(inputs["file_path"])
    elif name == "validate_schema":
        return validate_schema()
    elif name == "clean_data":
        return clean_data()
    elif name == "summarize_shape":
        return summarize_shape()
    else:
        return {"status": "error", "message": f"Unknown tool: {name}"}
