"""
Streamlit UI for the Battery Performance Analysis Agent.

Run with:
    streamlit run battery_agent/ui/app.py
"""

import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Ensure the project root is on sys.path when running via `streamlit run`
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Battery Performance Analysis Agent",
    page_icon="🔋",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Minimal CSS — keep it vanilla per the plan spec
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .metric-card {
        background: #f0f4f8;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }
    .gap-negative { color: #c0392b; font-weight: bold; }
    .gap-positive { color: #27ae60; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🔋 Battery Storage Performance Analysis Agent")
st.markdown(
    "Upload a battery performance CSV to compare historical operation against "
    "perfect-foresight benchmarks and receive actionable recommendations."
)
st.divider()

# ---------------------------------------------------------------------------
# Sidebar — configuration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    uploaded_file = st.file_uploader(
        "Upload CSV",
        type=["csv"],
        help="Expected columns: SCENARIO_NAME, SCHEDULE_TYPE, START_DATETIME, SOC, "
             "CHARGE_ENERGY, DISCHARGE_ENERGY, PRICE_ENERGY, REVENUE",
    )

    user_query = st.text_area(
        "Analysis question (optional)",
        value="Analyze the battery performance data and provide actionable recommendations "
              "to close the gap between historical and perfect-foresight operation.",
        height=100,
    )

    run_btn = st.button("▶ Run Analysis", type="primary", disabled=uploaded_file is None)

    st.divider()
    st.markdown("**About**")
    st.markdown(
        "Uses Claude's native `tool_use` loop with three specialised sub-agents:\n"
        "1. Data Prep\n2. Analysis\n3. Recommendations"
    )

# ---------------------------------------------------------------------------
# Main content area
# ---------------------------------------------------------------------------

if not uploaded_file and not run_btn:
    st.info("Upload a CSV in the sidebar and click **Run Analysis** to start.")
    st.stop()

if uploaded_file and not run_btn:
    st.info("File loaded. Click **▶ Run Analysis** in the sidebar to start.")
    # Show a quick preview
    import pandas as pd

    try:
        df_preview = pd.read_csv(uploaded_file)
        uploaded_file.seek(0)  # reset after read
        with st.expander("CSV Preview (first 10 rows)"):
            st.dataframe(df_preview.head(10), use_container_width=True)
            st.caption(f"{len(df_preview):,} rows × {len(df_preview.columns)} columns")
    except Exception:
        pass
    st.stop()

# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------
if run_btn and uploaded_file:
    from battery_agent.orchestrator import run_analysis

    # Save uploaded file to a temp location
    suffix = Path(uploaded_file.name).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    # Log container
    log_placeholder = st.empty()
    log_lines: list[str] = []

    def append_log(msg: str) -> None:
        log_lines.append(msg)
        # Show last 30 lines in the log panel
        visible = log_lines[-30:]
        log_placeholder.code("\n".join(visible), language=None)

    append_log("Starting analysis pipeline...")

    report: dict | None = None
    error_msg: str | None = None

    with st.spinner("Agent pipeline running — this may take 30–90 seconds..."):
        try:
            report = run_analysis(
                file_path=tmp_path,
                user_query=user_query,
                log_callback=append_log,
            )
        except Exception as exc:
            error_msg = str(exc)

    # Clear spinner artefact and show final log in expander
    log_placeholder.empty()

    if error_msg or (report and report.get("status") == "error"):
        msg = error_msg or report.get("message", "Unknown error")
        st.error(f"Analysis failed: {msg}")
        with st.expander("Agent log"):
            st.code("\n".join(log_lines), language=None)
        st.stop()

    with st.expander("Agent execution log", expanded=False):
        st.code("\n".join(log_lines), language=None)

    st.success("Analysis complete!")
    st.divider()

    # ------------------------------------------------------------------
    # Results layout: two columns — metrics left, recommendations right
    # ------------------------------------------------------------------
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        # Revenue summary
        st.subheader("Revenue Summary")

        rev = report.get("revenue_summary", {})
        hist_rev = rev.get("historical_cleared_total_revenue")
        perf_rev = rev.get("perfect_cleared_total_revenue")
        gap_dollars = rev.get("gap_dollars")
        gap_pct = rev.get("gap_pct")

        m1, m2, m3 = st.columns(3)
        m1.metric("Historical (cleared)", f"${hist_rev:,.2f}" if hist_rev is not None else "N/A")
        m2.metric("Perfect (cleared)", f"${perf_rev:,.2f}" if perf_rev is not None else "N/A")
        m3.metric(
            "Gap",
            f"${gap_dollars:,.2f}" if gap_dollars is not None else "N/A",
            delta=f"{gap_pct:.1f}%" if gap_pct is not None else None,
            delta_color="inverse",
        )

        # Revenue by combo table
        by_combo = rev.get("by_combo", {})
        if by_combo:
            import pandas as pd

            combo_rows = []
            for combo_key, vals in sorted(by_combo.items()):
                parts = combo_key.split("/", 1)
                combo_rows.append({
                    "Scenario": parts[0].capitalize() if parts else combo_key,
                    "Schedule": parts[1].capitalize() if len(parts) > 1 else "",
                    "Revenue ($)": f"${vals.get('total_revenue', 0):,.2f}",
                    "Avg Price ($/MWh)": f"${vals.get('avg_price', 0):,.4f}",
                    "Intervals": vals.get("intervals", 0),
                })
            st.dataframe(pd.DataFrame(combo_rows), use_container_width=True, hide_index=True)

        # Dispatch comparison
        dispatch = report.get("dispatch_comparison", {})
        if dispatch:
            st.subheader("Dispatch Statistics")
            d1, d2 = st.columns(2)
            d1.metric("Missed Discharge Events", dispatch.get("missed_discharge_intervals", 0))
            d2.metric("Unnecessary Charge Events", dispatch.get("unnecessary_charge_intervals", 0))
            d3, d4 = st.columns(2)
            d3.metric(
                "Missed Discharge (MWh)",
                f"{dispatch.get('missed_discharge_MWh', 0):,.4f}",
            )
            d4.metric(
                "Missed Discharge Revenue",
                f"${dispatch.get('missed_discharge_revenue', 0):,.2f}",
            )

        # SOC summary
        soc = report.get("soc_analysis", {})
        if soc:
            st.subheader("SOC Analysis")
            hist_soc = soc.get("historical_cleared_soc", {})
            perf_soc = soc.get("perfect_cleared_soc", {})
            s1, s2, s3 = st.columns(3)
            s1.metric("Mean SOC — Historical", f"{hist_soc.get('mean', 'N/A')}%")
            s2.metric("Mean SOC — Perfect", f"{perf_soc.get('mean', 'N/A')}%")
            s3.metric(
                "SOC-Constrained Intervals",
                soc.get("soc_constrained_discharge_intervals", 0),
            )

    with col_right:
        # Gap drivers
        st.subheader("Gap Driver Analysis")

        gd = report.get("gap_drivers", {})
        primary = gd.get("primary_driver", {})
        secondary = gd.get("secondary_driver", {})

        if primary:
            with st.container(border=True):
                st.markdown(f"**Primary Driver**: {primary.get('factor', '').replace('_', ' ').title()}")
                st.markdown(primary.get("evidence", ""))
                if primary.get("revenue_impact_dollars") is not None:
                    st.markdown(f"Revenue impact: **${primary['revenue_impact_dollars']:,.2f}**")

        if secondary:
            with st.container(border=True):
                st.markdown(f"**Secondary Driver**: {secondary.get('factor', '').replace('_', ' ').title()}")
                st.markdown(secondary.get("evidence", ""))

        summary_text = gd.get("summary")
        if summary_text:
            st.info(summary_text)

        # Recommendations
        st.subheader("Recommendations")

        recs_data = report.get("recommendations", {})
        rec_list = recs_data.get("recommendations", []) if isinstance(recs_data, dict) else []

        if not rec_list:
            st.warning("No validated recommendations were generated.")
        else:
            for rec in rec_list:
                with st.expander(f"Recommendation {rec['id']}: {rec['action'][:80]}...", expanded=True):
                    st.markdown(f"**Action:** {rec['action']}")
                    st.markdown(f"**Reasoning:** {rec['reasoning']}")
                    st.markdown(f"**Expected Benefit:** {rec['expected_benefit']}")
                    st.markdown(f"**Tradeoff:** {rec['tradeoff']}")

    # ------------------------------------------------------------------
    # Full agent narrative (analysis text)
    # ------------------------------------------------------------------
    st.divider()
    with st.expander("Full analysis narrative (Analysis Agent output)"):
        st.markdown(report.get("analysis", "No analysis text available."))

    with st.expander("Data preparation summary (Data Prep Agent output)"):
        st.markdown(report.get("data_manifest", "No data manifest available."))

    # ------------------------------------------------------------------
    # PDF download
    # ------------------------------------------------------------------
    st.divider()
    pdf_bytes = report.get("pdf_bytes")
    if pdf_bytes:
        csv_stem = Path(uploaded_file.name).stem
        st.download_button(
            label="⬇ Download PDF Report",
            data=pdf_bytes,
            file_name=f"{csv_stem}_analysis_report.pdf",
            mime="application/pdf",
            type="primary",
        )
    else:
        st.warning(f"PDF generation failed: {report.get('pdf_error', 'unknown error')}")
