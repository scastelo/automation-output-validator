"""
automation_validator/core/validator.py
Core validation engine — checks automation outputs for inconsistencies,
missing values, logic failures, and threshold breaches.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class ValidationIssue:
    record_id: Any
    rule_name: str
    severity: str          # CRITICAL | WARNING | INFO
    category: str          # MISSING_VALUE | LOGIC_FAILURE | THRESHOLD_BREACH | INCONSISTENCY
    field: str
    description: str
    actual_value: Any = None
    expected_value: Any = None


@dataclass
class ValidationReport:
    run_timestamp: str
    source_file: str
    total_records: int
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def add_issue(self, issue: ValidationIssue):
        self.issues.append(issue)

    def build_summary(self):
        severity_counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        category_counts = {}

        for issue in self.issues:
            severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
            category_counts[issue.category] = category_counts.get(issue.category, 0) + 1

        affected_records = len(set(i.record_id for i in self.issues))
        health_score = max(0, round(100 - (
            severity_counts["CRITICAL"] * 10 +
            severity_counts["WARNING"] * 3 +
            severity_counts["INFO"] * 1
        ), 1))

        self.summary = {
            "total_records": self.total_records,
            "total_issues": len(self.issues),
            "affected_records": affected_records,
            "clean_records": self.total_records - affected_records,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "health_score": health_score,
            "pass_rate": round((self.total_records - affected_records) / self.total_records * 100, 1)
        }
        return self.summary


# ─────────────────────────────────────────────
# Validation Rules
# ─────────────────────────────────────────────

REQUIRED_FIELDS = [
    "record_id", "process_name", "status",
    "start_time", "records_processed", "output_value"
]

VALID_STATUSES = {"SUCCESS", "FAILED", "PENDING"}
VALID_REGIONS  = {"US", "EU", "APAC"}

EXPECTED_DURATIONS = {          # minutes — soft upper bounds
    "Invoice_Extraction":       20,
    "Payment_Reconciliation":   60,
    "Data_Sync":                30,
    "Report_Generation":        45,
}


class AutomationValidator:
    """
    Runs a battery of validation checks against a DataFrame
    of automation output records.
    """

    def __init__(self, df: pd.DataFrame, source_file: str = "unknown"):
        self.df = df.copy()
        self.source_file = source_file
        self.report = ValidationReport(
            run_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source_file=source_file,
            total_records=len(df),
        )
        self._parse_datetimes()

    # ── datetime coercion ──────────────────────────────────────────────
    def _parse_datetimes(self):
        for col in ("start_time", "end_time"):
            if col in self.df.columns:
                self.df[col] = pd.to_datetime(self.df[col], errors="coerce")

    # ── helpers ───────────────────────────────────────────────────────
    def _issue(self, row, rule, severity, category, field_name, desc,
               actual=None, expected=None, actual_value=None, expected_value=None):
        self.report.add_issue(ValidationIssue(
            record_id=row.get("record_id", "?"),
            rule_name=rule,
            severity=severity,
            category=category,
            field=field_name,
            description=desc,
            actual_value=actual_value if actual_value is not None else actual,
            expected_value=expected_value if expected_value is not None else expected,
        ))

    # ─────────────────────────────────────────────────────────────────
    # CHECK 1 — Required / Missing Fields
    # ─────────────────────────────────────────────────────────────────
    def check_missing_values(self):
        for _, row in self.df.iterrows():
            for col in REQUIRED_FIELDS:
                val = row.get(col)
                if pd.isna(val) or str(val).strip() in ("", "None", "NULL"):
                    self._issue(
                        row, "REQUIRED_FIELD_MISSING", "CRITICAL",
                        "MISSING_VALUE", col,
                        f"Required field '{col}' is null or empty.",
                        actual_value=val, expected_value="non-null"
                    )
            # soft-required: assigned_to
            if pd.isna(row.get("assigned_to")) or str(row.get("assigned_to")).strip() == "":
                self._issue(
                    row, "UNASSIGNED_RECORD", "WARNING",
                    "MISSING_VALUE", "assigned_to",
                    "Record has no assigned owner.",
                    actual_value=None, expected_value="<user>"
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 2 — Status Validity
    # ─────────────────────────────────────────────────────────────────
    def check_status_validity(self):
        for _, row in self.df.iterrows():
            status = str(row.get("status", "")).strip().upper()
            if status not in VALID_STATUSES:
                self._issue(
                    row, "INVALID_STATUS", "CRITICAL",
                    "INCONSISTENCY", "status",
                    f"Status '{row.get('status')}' is not a recognised value.",
                    actual_value=row.get("status"),
                    expected_value=list(VALID_STATUSES)
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 3 — Logic: end_time must be after start_time
    # ─────────────────────────────────────────────────────────────────
    def check_time_logic(self):
        for _, row in self.df.iterrows():
            start = row.get("start_time")
            end   = row.get("end_time")
            if pd.isna(start):
                continue
            if pd.isna(end):
                # PENDING is ok without end_time; otherwise flag
                if str(row.get("status", "")).upper() not in ("PENDING", "FAILED"):
                    self._issue(
                        row, "MISSING_END_TIME", "WARNING",
                        "MISSING_VALUE", "end_time",
                        "Successful record is missing end_time.",
                        actual_value=None
                    )
                continue
            if end <= start:
                self._issue(
                    row, "END_BEFORE_START", "CRITICAL",
                    "LOGIC_FAILURE", "end_time",
                    f"end_time ({end}) is not after start_time ({start}).",
                    actual_value=str(end), expected_value=f"> {start}"
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 4 — Duration outliers
    # ─────────────────────────────────────────────────────────────────
    def check_duration_outliers(self):
        for _, row in self.df.iterrows():
            start = row.get("start_time")
            end   = row.get("end_time")
            proc  = row.get("process_name")
            if pd.isna(start) or pd.isna(end) or pd.isna(proc):
                continue
            duration_min = (end - start).total_seconds() / 60
            cap = EXPECTED_DURATIONS.get(proc)
            if cap and duration_min > cap:
                self._issue(
                    row, "DURATION_EXCEEDED", "WARNING",
                    "LOGIC_FAILURE", "end_time",
                    f"Process ran for {duration_min:.1f} min, exceeding "
                    f"expected max of {cap} min for '{proc}'.",
                    actual_value=f"{duration_min:.1f} min",
                    expected_value=f"≤ {cap} min"
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 5 — Records-processed vs records-expected mismatch
    # ─────────────────────────────────────────────────────────────────
    def check_record_count_mismatch(self):
        for _, row in self.df.iterrows():
            processed = row.get("records_processed")
            expected  = row.get("records_expected")
            status    = str(row.get("status", "")).upper()
            if pd.isna(expected):
                self._issue(
                    row, "MISSING_EXPECTED_COUNT", "WARNING",
                    "MISSING_VALUE", "records_expected",
                    "records_expected is not set; cannot verify completeness.",
                    actual_value=processed
                )
                continue
            if status == "SUCCESS" and not pd.isna(processed):
                pct_diff = abs(processed - expected) / max(expected, 1) * 100
                if pct_diff > 5:
                    self._issue(
                        row, "RECORD_COUNT_MISMATCH", "WARNING",
                        "INCONSISTENCY", "records_processed",
                        f"Processed {processed} vs expected {expected} "
                        f"({pct_diff:.1f}% variance).",
                        actual_value=processed, expected_value=expected
                    )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 6 — Output value threshold breach
    # ─────────────────────────────────────────────────────────────────
    def check_threshold_breaches(self):
        for _, row in self.df.iterrows():
            val   = row.get("output_value")
            lo    = row.get("threshold_min")
            hi    = row.get("threshold_max")
            if pd.isna(val):
                continue
            try:
                val, lo, hi = float(val), float(lo), float(hi)
            except (TypeError, ValueError):
                continue
            if val < lo:
                self._issue(
                    row, "BELOW_THRESHOLD", "CRITICAL",
                    "THRESHOLD_BREACH", "output_value",
                    f"Output value {val} is below minimum threshold {lo}.",
                    actual_value=val, expected_value=f">= {lo}"
                )
            elif val > hi:
                self._issue(
                    row, "ABOVE_THRESHOLD", "CRITICAL",
                    "THRESHOLD_BREACH", "output_value",
                    f"Output value {val} exceeds maximum threshold {hi}.",
                    actual_value=val, expected_value=f"<= {hi}"
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 7 — Negative output values
    # ─────────────────────────────────────────────────────────────────
    def check_negative_values(self):
        for _, row in self.df.iterrows():
            val = row.get("output_value")
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            if val < 0:
                self._issue(
                    row, "NEGATIVE_OUTPUT", "CRITICAL",
                    "LOGIC_FAILURE", "output_value",
                    f"Output value is negative ({val}), which is logically invalid.",
                    actual_value=val, expected_value=">= 0"
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 8 — Region validity
    # ─────────────────────────────────────────────────────────────────
    def check_region_validity(self):
        for _, row in self.df.iterrows():
            region = str(row.get("region", "")).strip().upper()
            if region not in VALID_REGIONS:
                self._issue(
                    row, "INVALID_REGION", "WARNING",
                    "INCONSISTENCY", "region",
                    f"Region '{row.get('region')}' is not a valid region code.",
                    actual_value=row.get("region"),
                    expected_value=list(VALID_REGIONS)
                )

    # ─────────────────────────────────────────────────────────────────
    # CHECK 9 — Duplicate record IDs
    # ─────────────────────────────────────────────────────────────────
    def check_duplicate_ids(self):
        dupes = self.df[self.df.duplicated(subset=["record_id"], keep=False)]
        for _, row in dupes.iterrows():
            self._issue(
                row, "DUPLICATE_RECORD_ID", "CRITICAL",
                "INCONSISTENCY", "record_id",
                f"record_id {row.get('record_id')} appears more than once.",
                actual_value=row.get("record_id")
            )

    # ─────────────────────────────────────────────────────────────────
    # RUN ALL CHECKS
    # ─────────────────────────────────────────────────────────────────
    def run(self) -> ValidationReport:
        print("  [1/9] Checking missing values …")
        self.check_missing_values()
        print("  [2/9] Checking status validity …")
        self.check_status_validity()
        print("  [3/9] Checking time logic …")
        self.check_time_logic()
        print("  [4/9] Checking duration outliers …")
        self.check_duration_outliers()
        print("  [5/9] Checking record count mismatches …")
        self.check_record_count_mismatch()
        print("  [6/9] Checking threshold breaches …")
        self.check_threshold_breaches()
        print("  [7/9] Checking negative values …")
        self.check_negative_values()
        print("  [8/9] Checking region validity …")
        self.check_region_validity()
        print("  [9/9] Checking duplicate IDs …")
        self.check_duplicate_ids()

        self.report.build_summary()
        return self.report

    # ─────────────────────────────────────────────────────────────────
    # EXPORT HELPERS
    # ─────────────────────────────────────────────────────────────────
    def issues_to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([vars(i) for i in self.report.issues])

    def to_json(self) -> str:
        data = {
            "run_timestamp": self.report.run_timestamp,
            "source_file":   self.report.source_file,
            "summary":       self.report.summary,
            "issues": [vars(i) for i in self.report.issues],
        }
        return json.dumps(data, indent=2, default=str)
