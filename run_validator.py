"""
automation_validator/run_validator.py
Entry point — loads data, runs all checks, prints summary, saves reports.
"""

import sys
import os
import json
import pandas as pd

# allow running from project root
sys.path.insert(0, os.path.dirname(__file__))

from core.validator import AutomationValidator
from core.report_generator import generate_html_report


DATA_FILE    = "data/automation_output.csv"
REPORT_HTML  = "reports/validation_report.html"
REPORT_JSON  = "reports/validation_report.json"
REPORT_CSV   = "reports/issues.csv"


def banner(text, char="─"):
    print(f"\n{char*60}")
    print(f"  {text}")
    print(f"{char*60}")


def main():
    banner("AUTOMATION OUTPUT VALIDATOR", "═")
    print(f"  Source : {DATA_FILE}")

    # ── load ──────────────────────────────────────────────────────────
    df = pd.read_csv(DATA_FILE)
    print(f"  Loaded : {len(df)} records, {len(df.columns)} columns\n")

    # ── validate ──────────────────────────────────────────────────────
    banner("Running validation checks …")
    validator = AutomationValidator(df, source_file=DATA_FILE)
    report = validator.run()

    # ── summary ───────────────────────────────────────────────────────
    s = report.summary
    banner("SUMMARY", "═")
    print(f"  Total records     : {s['total_records']}")
    print(f"  Clean records     : {s['clean_records']}  ({s['pass_rate']}%)")
    print(f"  Affected records  : {s['affected_records']}")
    print(f"  Total issues      : {s['total_issues']}")
    print()
    print(f"  🔴  Critical : {s['severity_counts']['CRITICAL']}")
    print(f"  🟡  Warnings : {s['severity_counts']['WARNING']}")
    print(f"  🔵  Info     : {s['severity_counts']['INFO']}")
    print()
    print(f"  Health Score  : {s['health_score']} / 100")
    print()
    print("  Issues by category:")
    for cat, cnt in s.get("category_counts", {}).items():
        print(f"    {cat:<25} {cnt}")

    # ── save outputs ──────────────────────────────────────────────────
    os.makedirs("reports", exist_ok=True)

    # HTML report
    html = generate_html_report(report)
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # JSON report
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        f.write(validator.to_json())

    # CSV issues list
    issues_df = validator.issues_to_dataframe()
    issues_df.to_csv(REPORT_CSV, index=False)

    banner("OUTPUT FILES")
    print(f"  HTML dashboard : {REPORT_HTML}")
    print(f"  JSON data      : {REPORT_JSON}")
    print(f"  CSV issues     : {REPORT_CSV}\n")
    print("  Done. ✓\n")

    return report


if __name__ == "__main__":
    main()
