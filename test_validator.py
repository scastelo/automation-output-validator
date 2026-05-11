"""
automation_validator/tests/test_validator.py
Unit tests for all 9 validation rules.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from core.validator import AutomationValidator


# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def _base_row(**overrides):
    """Returns a minimal valid record; overrides replace specific fields."""
    row = {
        "record_id":          1,
        "process_name":       "Invoice_Extraction",
        "status":             "SUCCESS",
        "start_time":         "2024-01-15 08:00:00",
        "end_time":           "2024-01-15 08:10:00",
        "records_processed":  500,
        "records_expected":   500,
        "error_code":         None,
        "output_value":       1000.0,
        "threshold_min":      100,
        "threshold_max":      5000,
        "assigned_to":        "john.doe",
        "region":             "US",
    }
    row.update(overrides)
    return row


def _run(rows):
    df = pd.DataFrame(rows)
    v = AutomationValidator(df)
    v.run()
    return v


def _rules(v):
    return [i.rule_name for i in v.report.issues]

def _severities(v):
    return [i.severity for i in v.report.issues]


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

class TestMissingValues:
    def test_clean_record_no_issues(self):
        v = _run([_base_row()])
        assert v.report.issues == []

    def test_missing_output_value_flagged(self):
        v = _run([_base_row(output_value=None)])
        assert "REQUIRED_FIELD_MISSING" in _rules(v)

    def test_missing_status_flagged(self):
        v = _run([_base_row(status=None)])
        assert "REQUIRED_FIELD_MISSING" in _rules(v)

    def test_unassigned_owner_warning(self):
        v = _run([_base_row(assigned_to=None)])
        assert "UNASSIGNED_RECORD" in _rules(v)
        assert "CRITICAL" not in _severities(v)    # should be WARNING, not CRITICAL


class TestStatusValidity:
    def test_invalid_status_null(self):
        v = _run([_base_row(status="NULL")])
        assert "INVALID_STATUS" in _rules(v)

    def test_valid_statuses_pass(self):
        for s in ("SUCCESS", "FAILED", "PENDING"):
            v = _run([_base_row(status=s)])
            rules = _rules(v)
            assert "INVALID_STATUS" not in rules, f"Status {s} should be valid"

    def test_invalid_status_is_critical(self):
        v = _run([_base_row(status="UNKNOWN")])
        sev = {i.rule_name: i.severity for i in v.report.issues}
        assert sev.get("INVALID_STATUS") == "CRITICAL"


class TestTimeLogic:
    def test_end_before_start_flagged(self):
        v = _run([_base_row(
            start_time="2024-01-15 11:00:00",
            end_time  ="2024-01-15 10:55:00",
        )])
        assert "END_BEFORE_START" in _rules(v)

    def test_success_without_end_time_flagged(self):
        v = _run([_base_row(end_time=None, status="SUCCESS")])
        assert "MISSING_END_TIME" in _rules(v)

    def test_pending_without_end_time_ok(self):
        v = _run([_base_row(end_time=None, status="PENDING",
                             records_processed=0, output_value=0)])
        assert "MISSING_END_TIME" not in _rules(v)


class TestDurationOutliers:
    def test_excessive_duration_flagged(self):
        # Invoice_Extraction cap = 20 min; give it 60 min
        v = _run([_base_row(
            start_time="2024-01-15 08:00:00",
            end_time  ="2024-01-15 09:00:00",
        )])
        assert "DURATION_EXCEEDED" in _rules(v)

    def test_normal_duration_ok(self):
        v = _run([_base_row(
            start_time="2024-01-15 08:00:00",
            end_time  ="2024-01-15 08:10:00",
        )])
        assert "DURATION_EXCEEDED" not in _rules(v)


class TestRecordCounts:
    def test_large_count_variance_flagged(self):
        v = _run([_base_row(records_processed=400, records_expected=500)])
        assert "RECORD_COUNT_MISMATCH" in _rules(v)

    def test_small_variance_ok(self):
        # 2% variance — under 5% threshold
        v = _run([_base_row(records_processed=490, records_expected=500)])
        assert "RECORD_COUNT_MISMATCH" not in _rules(v)

    def test_missing_expected_count_warning(self):
        v = _run([_base_row(records_expected=None)])
        assert "MISSING_EXPECTED_COUNT" in _rules(v)


class TestThresholds:
    def test_below_min_threshold(self):
        v = _run([_base_row(output_value=50, threshold_min=100)])
        assert "BELOW_THRESHOLD" in _rules(v)

    def test_above_max_threshold(self):
        v = _run([_base_row(output_value=9999, threshold_max=5000)])
        assert "ABOVE_THRESHOLD" in _rules(v)

    def test_within_threshold_ok(self):
        v = _run([_base_row(output_value=1000, threshold_min=100, threshold_max=5000)])
        assert "BELOW_THRESHOLD" not in _rules(v)
        assert "ABOVE_THRESHOLD" not in _rules(v)


class TestNegativeValues:
    def test_negative_output_flagged(self):
        v = _run([_base_row(output_value=-50)])
        assert "NEGATIVE_OUTPUT" in _rules(v)

    def test_zero_ok(self):
        v = _run([_base_row(output_value=0, threshold_min=0)])
        assert "NEGATIVE_OUTPUT" not in _rules(v)


class TestRegionValidity:
    def test_invalid_region_flagged(self):
        v = _run([_base_row(region="UNKNOWN")])
        assert "INVALID_REGION" in _rules(v)

    def test_valid_regions_pass(self):
        for r in ("US", "EU", "APAC"):
            v = _run([_base_row(region=r)])
            assert "INVALID_REGION" not in _rules(v)


class TestDuplicateIds:
    def test_duplicate_ids_flagged(self):
        rows = [_base_row(record_id=1), _base_row(record_id=1)]
        v = _run(rows)
        assert "DUPLICATE_RECORD_ID" in _rules(v)

    def test_unique_ids_ok(self):
        rows = [_base_row(record_id=1), _base_row(record_id=2)]
        v = _run(rows)
        assert "DUPLICATE_RECORD_ID" not in _rules(v)


class TestHealthScore:
    def test_clean_data_high_score(self):
        rows = [_base_row(record_id=i) for i in range(1, 6)]
        v = _run(rows)
        v.report.build_summary()
        assert v.report.summary["health_score"] == 100

    def test_many_criticals_lower_score(self):
        rows = [_base_row(record_id=i, output_value=-999) for i in range(1, 11)]
        v = _run(rows)
        v.report.build_summary()
        assert v.report.summary["health_score"] < 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
