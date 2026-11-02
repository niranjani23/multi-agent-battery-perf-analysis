# Battery Storage Performance Analysis Agent

An LLM-powered multi-agent system that analyses one week of battery storage performance data
and produces clear, actionable recommendations comparing historical operation against a
perfect-foresight benchmark.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

Create a `.env` file in the `battery_agent/` directory (or export the variable):

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Running the Analysis

### Streamlit UI 

```bash
streamlit run battery_agent/ui/app.py
```

- Upload the CSV via the sidebar file picker.
- Optionally customise the analysis question.
- Click **Run Analysis** — the three-agent pipeline runs automatically.
- Download the PDF report when complete.

### CLI

```bash
python -m battery_agent.main path/to/data.csv
```

Optional flags:

| Flag | Description |
|------|-------------|
| `--query "..."` | Custom analysis question |
| `--output report.pdf` | PDF output path (default: `<csv_stem>_report.pdf`) |
| `--json` | Print full report as JSON (no Rich formatting) |

---

## Architecture

```
Orchestrator
 ├─► Data Prep Agent    (load → validate → clean → summarize)
 ├─► Analysis Agent     (revenue → high-price → dispatch → SOC → gap drivers)
 └─► Recommendation Agent  (generate 2 evidence-grounded recommendations)
         └─► PDF Report (ReportLab Platypus)
```

### How the agent uses tools

Each sub-agent follows the same **tool_use loop** (`agents/base.py`):

1. Send user message + tool definitions to Claude.
2. Claude responds with one or more `tool_use` blocks.
3. Python executes the tool and appends a `tool_result` to the conversation.
4. Repeat until Claude returns `stop_reason == "end_turn"`.

**Key design decisions:**

- **No raw data in prompts** — tools return JSON summaries only; Claude never sees CSV rows.
- **Fail fast** — `validate_schema` runs before any analysis tokens are spent on bad data.
- **Evidence-grounded recommendations** — the Recommendation Agent system prompt explicitly
  forbids conclusions not tied to tool output evidence; the `generate_recommendations` tool
  validates that each recommendation references actual analysis keywords.
- **Module-level state** — the cleaned DataFrame is stored in `data_tools._state` so all
  downstream tools can read it without the LLM needing to pass a DataFrame.
- **Enforced tool ordering** — each agent's system prompt specifies the exact call order;
  `find_gap_drivers` requires all four prior outputs as explicit parameters.

### Tool chain

```
load_csv → validate_schema → clean_data → summarize_shape
  → compute_revenue_summary → identify_high_price_intervals
  → compare_dispatch → analyze_soc → find_gap_drivers
  → generate_recommendations → PDF
```

---

## Expected Dataset Format

| Column | Type | Description |
|--------|------|-------------|
| `SCENARIO_NAME` | str | `historical` or `perfect` |
| `SCHEDULE_TYPE` | str | `cleared` or `expected` |
| `START_DATETIME` | datetime | 5-minute interval start |
| `SOC` | float | State of Charge (%) |
| `CHARGE_ENERGY` | float | Energy charged (MWh) |
| `DISCHARGE_ENERGY` | float | Energy discharged (MWh) |
| `PRICE_ENERGY` | float | Spot price ($/MWh) |
| `REVENUE` | float | Revenue for that interval ($) |

---

## Model

Uses `claude-sonnet-4-6` by default. Override via the `ANTHROPIC_MODEL` environment variable:

```
ANTHROPIC_MODEL=claude-opus-4-6
```
