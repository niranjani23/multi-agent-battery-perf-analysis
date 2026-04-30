# Battery Agent System — Planning Discussion

## Context

**Task:** Build an LLM-based agent that analyzes one week of battery storage performance data and produces clear, actionable recommendations comparing historical operation vs. perfect foresight scenario.

**Dataset:** `Takehome_Problem_Agentic_Battery_Analysis_System_BLYTHB1_20260126.csv`
- Battery: Blyth Battery (BLYTHB1)
- Sample date: January 26, 2026
- ~1,150 rows, 5-minute intervals
- Columns: `SCENARIO_NAME`, `SCHEDULE_TYPE`, `START_DATETIME`, `SOC`, `CHARGE_ENERGY`, `DISCHARGE_ENERGY`, `PRICE_ENERGY`, `REVENUE`
- 4 scenario×schedule combos: `historical/cleared`, `historical/expected`, `perfect/cleared`, `perfect/expected`

---

## Tech Stack Decisions

### LLM Backend
**Chosen: Anthropic Claude API (raw, no framework)**

| Option | Decision | Reason |
|---|---|---|
| LangChain | ❌ | Too heavy, abstraction leakage, overkill for scoped task |
| LlamaIndex | ❌ | Built for RAG, poor fit for tool-calling agents |
| OpenAI Agents SDK | ⚠️ | Locks to OpenAI |
| Raw Claude API (`tool_use`) | ✅ | Full control, transparent orchestration loop, explicit tool contracts — exactly what the rubric rewards |

- Model: `claude-sonnet-4-20250514`
- Use native `tool_use` / `tool_result` message loop
- No wrapper frameworks

### UI
**Chosen: Streamlit (primary) + Rich terminal (fallback)**

| Option | Decision | Reason |
|---|---|---|
| Streamlit | ✅ Primary | Fast, native file upload, chart rendering, ~50 lines of UI code |
| Gradio | ⚠️ | Less flexible layout |
| FastAPI + HTML | ❌ | Too much boilerplate for a take-home |
| Rich (terminal) | ✅ Fallback | Zero deps, beautiful CLI output |

- Plain vanilla Streamlit frontend (no custom CSS)
- File upload widget → Run Analysis button → streaming log panel → final report
- Download button for PDF output

### Output
**Chosen: Downloadable PDF via ReportLab**

- Generated server-side using `reportlab` (Platypus layout engine)
- Structured report: summary stats, gap analysis, key drivers, recommendations
- Streamlit `st.download_button` to serve the PDF bytes

---

## Multi-Agent Architecture

```
┌─────────────────────────────────────────┐
│           ORCHESTRATOR AGENT            │
│  - Receives user query + CSV path       │
│  - Calls sub-agents in sequence         │
│  - Passes results between agents        │
│  - Assembles final report + PDF         │
└──────────┬──────────────────────────────┘
           │ delegates to
     ┌─────┴────────────────────────────────────────┐
     │                  │                           │
     ▼                  ▼                           ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐
│  DATA PREP  │  │  ANALYSIS    │  │  RECOMMENDATION      │
│  SUB-AGENT  │  │  SUB-AGENT   │  │  SUB-AGENT           │
└─────────────┘  └──────────────┘  └──────────────────────┘
```

### Agent 1: Data Prep Sub-Agent
**Responsibility:** Validate, clean, and summarize the raw CSV. Fail fast before any LLM tokens are spent on bad data.

**Tools:**
- `load_csv(file_path)` — loads CSV, parses datetimes, returns shape + preview
- `validate_schema(df)` — checks required columns exist, no nulls in critical fields
- `clean_data(df)` — normalizes datetime to UTC, splits by SCENARIO_NAME × SCHEDULE_TYPE
- `summarize_shape(df)` — returns row counts, date range, scenarios found, interval count

**Returns:** Clean data manifest (JSON) with stats — does NOT return raw rows

---

### Agent 2: Analysis Sub-Agent
**Responsibility:** Run all quantitative analysis. Each tool output feeds the next.

**Tools:**
- `compute_revenue_summary(df)` — total historical revenue, total perfect revenue, total gap ($)
- `identify_high_price_intervals(df, threshold)` — find intervals where price > threshold; compare historical vs perfect dispatch in those windows
- `compare_dispatch(df)` — compare CHARGE_ENERGY and DISCHARGE_ENERGY between scenarios; find missed discharge / unnecessary charge events
- `analyze_soc(df)` — SOC profile over time; identify SOC constraints that blocked discharge during high-price intervals
- `find_gap_drivers(revenue_summary, high_price_analysis, dispatch_comparison, soc_analysis)` — takes ALL prior tool outputs as input; identifies primary driver and secondary factor of the performance gap

**Returns:** Structured JSON with evidence for each finding

**Key design note:** `find_gap_drivers` explicitly requires outputs from all prior tools as inputs — this enforces multi-step reasoning and prevents unsupported conclusions.

---

### Agent 3: Recommendation Sub-Agent
**Responsibility:** Produce exactly 2 actionable recommendations grounded only in tool evidence.

**Tools:**
- `generate_recommendations(gap_drivers, dispatch_comparison, soc_analysis)` — structured output enforced via system prompt; cannot invent recommendations not supported by tool outputs

**Each recommendation includes:**
- Action
- Reasoning (tied to specific evidence)
- Expected benefit
- One tradeoff

**Returns:** 2 recommendations as structured JSON

---

### Orchestrator
**Responsibility:** Coordinate the pipeline, pass state between agents, assemble the final report.

**Flow:**
1. Receive CSV path + user query
2. Call Data Prep Agent → get clean manifest
3. Call Analysis Agent with manifest → get structured analysis
4. Call Recommendation Agent with analysis → get recommendations
5. Assemble final report dict
6. Generate PDF via ReportLab
7. Return report to Streamlit for display + download

**Key principle:** Orchestrator never touches raw CSV rows directly. All data access goes through tools.

---

## Tool Chaining Flow

```
load_csv
   └─► validate_schema
           └─► clean_data
                   └─► summarize_shape
                               └─► compute_revenue_summary
                                           └─► identify_high_price_intervals
                                                       └─► compare_dispatch
                                                                   └─► analyze_soc
                                                                               └─► find_gap_drivers
                                                                                           └─► generate_recommendations
                                                                                                       └─► PDF Report
```

Each step only receives the JSON summary from the prior step — never raw dataframe rows.

---

## Folder Structure

```
battery_agent/
├── main.py                  # CLI entry point
├── orchestrator.py          # Orchestrator agent loop
├── agents/
│   ├── __init__.py
│   ├── base.py              # Shared Claude tool_use loop logic
│   ├── data_prep.py         # Data prep sub-agent
│   ├── analysis.py          # Analysis sub-agent
│   └── recommendations.py   # Recommendation sub-agent
├── tools/
│   ├── __init__.py
│   ├── data_tools.py        # load, validate, clean, summarize
│   ├── analysis_tools.py    # revenue, dispatch, soc, gap drivers
│   └── rec_tools.py         # recommendation generator
├── report/
│   ├── __init__.py
│   └── pdf_generator.py     # ReportLab PDF builder
├── ui/
│   └── app.py               # Streamlit app
├── README.md
└── requirements.txt
```

---

## Base Agent Loop (pseudo-code)

Each sub-agent follows this same pattern:

```python
def run_agent_loop(client, system_prompt, tools, initial_message, tool_executor):
    messages = [{"role": "user", "content": initial_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return extract_text(response.content)

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = tool_executor(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
            messages.append({"role": "user", "content": tool_results})
```

---

## Key Design Principles

1. **No raw data in prompts** — tools return JSON summaries only; the LLM never sees CSV rows
2. **Fail fast** — schema validation runs before any LLM call; bad data returns a clear error immediately
3. **Evidence-grounded recommendations** — Recommendation agent system prompt explicitly forbids conclusions not tied to tool output evidence
4. **Generalization** — schema validator checks column names dynamically; no hardcoded assumptions in prompts
5. **Separation of concerns** — each agent has a tight system prompt scoped to its responsibility, reducing hallucination surface area

---

## Requirements

```
anthropic
pandas
streamlit
reportlab
python-dotenv
```

API key via `ANTHROPIC_API_KEY` environment variable (`.env` file supported via `python-dotenv`).

---

## Deliverables

1. **Runnable Python script** (`main.py` for CLI, `ui/app.py` for Streamlit)
2. **README** with setup instructions, high-level approach, how the agent uses tools
3. **Example output** — sample prompt + corresponding PDF report output
