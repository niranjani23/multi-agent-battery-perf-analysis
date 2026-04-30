"""
CLI entry point for the Battery Performance Analysis Agent.

Usage:
    python -m battery_agent.main <csv_path> [--query "Your question"]
    python battery_agent/main.py <csv_path>
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Battery Storage Performance Analysis Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m battery_agent.main data.csv
  python -m battery_agent.main data.csv --query "What drove the revenue gap?"
  python -m battery_agent.main data.csv --output report.pdf
        """,
    )
    parser.add_argument("csv_path", help="Path to the battery performance CSV file.")
    parser.add_argument(
        "--query",
        default="Analyze the battery performance data and provide actionable recommendations.",
        help="Analysis question or instruction.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to save the generated PDF (default: <csv_stem>_report.pdf).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print the full report dict as JSON to stdout (no Rich formatting).",
    )
    args = parser.parse_args()

    csv_path = str(Path(args.csv_path).resolve())

    # Try to import Rich for pretty terminal output
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.rule import Rule
        from rich.text import Text

        console = Console()

        def log(msg: str) -> None:
            console.print(f"[dim]{msg}[/dim]")

        def section(title: str) -> None:
            console.print(Rule(f"[bold blue]{title}[/bold blue]"))

        def success(msg: str) -> None:
            console.print(f"[bold green]{msg}[/bold green]")

        def error(msg: str) -> None:
            console.print(f"[bold red]{msg}[/bold red]")

        def info(msg: str) -> None:
            console.print(msg)

        console.print(
            Panel.fit(
                "[bold]Battery Storage Performance Analysis Agent[/bold]",
                border_style="blue",
            )
        )

    except ImportError:
        # Fallback: plain print
        def log(msg: str) -> None:
            print(msg)

        def section(title: str) -> None:
            print(f"\n{'='*60}\n{title}\n{'='*60}")

        def success(msg: str) -> None:
            print(f"✓ {msg}")

        def error(msg: str) -> None:
            print(f"✗ {msg}", file=sys.stderr)

        def info(msg: str) -> None:
            print(msg)

    # Import orchestrator here so env vars from .env are loaded first
    from battery_agent.orchestrator import run_analysis

    section("Running Analysis")
    info(f"File:  {csv_path}")
    info(f"Query: {args.query}")
    print()

    report = run_analysis(
        file_path=csv_path,
        user_query=args.query,
        log_callback=log,
    )

    if report.get("status") == "error":
        error(f"\nAnalysis failed: {report.get('message')}")
        sys.exit(1)

    if args.output_json:
        # Strip non-serialisable PDF bytes before printing
        printable = {k: v for k, v in report.items() if k != "pdf_bytes"}
        print(json.dumps(printable, indent=2, default=str))
        return

    # ------------------------------------------------------------------
    # Print summary to terminal
    # ------------------------------------------------------------------
    section("Analysis Summary")

    rev = report.get("revenue_summary", {})
    info(f"Historical revenue (cleared): ${rev.get('historical_cleared_total_revenue', 'N/A'):,.2f}")
    info(f"Perfect revenue   (cleared): ${rev.get('perfect_cleared_total_revenue', 'N/A'):,.2f}")
    info(f"Gap:                         ${rev.get('gap_dollars', 'N/A'):,.2f} ({rev.get('gap_pct', 'N/A'):.1f}%)")

    gd = report.get("gap_drivers", {})
    primary = gd.get("primary_driver", {})
    secondary = gd.get("secondary_driver", {})

    if primary:
        section("Primary Gap Driver")
        info(f"Factor:   {primary.get('factor', '').replace('_', ' ').title()}")
        info(f"Evidence: {primary.get('evidence', '')}")
        info(f"Impact:   ${primary.get('revenue_impact_dollars', 0):,.2f}")

    if secondary:
        section("Secondary Driver")
        info(f"Factor:   {secondary.get('factor', '').replace('_', ' ').title()}")
        info(f"Evidence: {secondary.get('evidence', '')}")

    recs = report.get("recommendations", {})
    rec_list = recs.get("recommendations", []) if isinstance(recs, dict) else []
    if rec_list:
        section("Recommendations")
        for rec in rec_list:
            info(f"\n  [{rec['id']}] {rec['action']}")
            info(f"      Reasoning:        {rec['reasoning']}")
            info(f"      Expected benefit: {rec['expected_benefit']}")
            info(f"      Tradeoff:         {rec['tradeoff']}")

    # ------------------------------------------------------------------
    # Save PDF
    # ------------------------------------------------------------------
    pdf_bytes = report.get("pdf_bytes")
    if pdf_bytes:
        csv_stem = Path(csv_path).stem
        pdf_path = args.output or f"{csv_stem}_report.pdf"
        with open(pdf_path, "wb") as fh:
            fh.write(pdf_bytes)
        success(f"\nPDF report saved to: {pdf_path}")
    else:
        err = report.get("pdf_error", "unknown error")
        error(f"\nPDF generation failed: {err}")


if __name__ == "__main__":
    main()
