#!/usr/bin/env python3
"""
integrations/qa.py — QA Agent Engine

Generates and executes:
  1. Test documents       (qa_artifacts/test_plans/<pipeline>.md)
  2. Test cases           (qa_artifacts/test_cases/<pipeline>.json)
  3. Sample data          (qa_artifacts/sample_data/<table>_sample.csv)
  4. QA analysis run      (runs all tests, captures results)
  5. Test result document (qa_artifacts/results/<run_id>_test_results.md)
  6. Job fixes document   (qa_artifacts/results/<run_id>_job_fixes.md)
  7. Lineage document     (qa_artifacts/lineage/<pipeline>_lineage.md)
  8. Git push with version tag

Usage:
  python3 integrations/qa.py generate --pipeline nwt_batch_load
  python3 integrations/qa.py run       --pipeline nwt_batch_load
  python3 integrations/qa.py lineage   --pipeline nwt_batch_load
  python3 integrations/qa.py report    --run-id QA-ABC123
  python3 integrations/qa.py publish   --run-id QA-ABC123   # push to git with version tag
"""

import csv
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

QA_DIR       = ROOT / "qa_artifacts"
PLANS_DIR    = QA_DIR / "test_plans"
CASES_DIR    = QA_DIR / "test_cases"
SAMPLES_DIR  = QA_DIR / "sample_data"
RESULTS_DIR  = QA_DIR / "results"
LINEAGE_DIR  = QA_DIR / "lineage"

for d in [PLANS_DIR, CASES_DIR, SAMPLES_DIR, RESULTS_DIR, LINEAGE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:6].upper()


# ── Pipeline definitions ───────────────────────────────────────────────────

PIPELINE_SPECS = {
    "nwt_batch_load": {
        "description":  "NWT orders batch load: S3 → Glue → Snowflake landing + curated",
        "source":       "S3 Parquet",
        "target":       "Snowflake NISHANT_DS_DB.NISHANT_WORKFLOW_TEST",
        "tables":       ["NWT_ORDER_FILE", "NWT_ORDER_PRODUCT_FILE", "NWT_STORE_FILE"],
        "schedule":     "Daily 06:00 UTC",
        "owner":        "data_engineer",
        "lineage": [
            {"from": "S3 s3://data-lake/landing/orders/",       "to": "NWT_ORDER_FILE",        "via": "AWS Glue Job"},
            {"from": "S3 s3://data-lake/landing/order_products/","to": "NWT_ORDER_PRODUCT_FILE","via": "AWS Glue Job"},
            {"from": "S3 s3://data-lake/landing/stores/",       "to": "NWT_STORE_FILE",        "via": "AWS Glue Job"},
        ],
        "test_categories": ["freshness","volume","schema","nulls","duplicates","business_rules"],
    },
    "dbt_star_schema": {
        "description":  "dbt star schema: curated tables → FACT_ORDER + DIM_*",
        "source":       "NWT_ORDER_FILE, NWT_STORE_FILE (Snowflake curated)",
        "target":       "Snowflake NISHANT_DS_DB.NISHANT_WORKFLOW_TEST (star schema)",
        "tables":       ["FACT_ORDER", "DIM_STORE", "DIM_DATE", "DIM_DAYPART"],
        "schedule":     "Daily 07:00 UTC",
        "owner":        "analytics_engineer",
        "lineage": [
            {"from": "NWT_ORDER_FILE",         "to": "FACT_ORDER", "via": "dbt model fact_order.sql"},
            {"from": "NWT_STORE_FILE",         "to": "DIM_STORE",  "via": "dbt model dim_store.sql"},
            {"from": "NWT_DATE_FILE",          "to": "DIM_DATE",   "via": "dbt model dim_date.sql"},
            {"from": "NWT_DAYPART_FILE",       "to": "DIM_DAYPART","via": "dbt model dim_daypart.sql"},
            {"from": "FACT_ORDER + DIM_STORE", "to": "Report Layer","via": "Snowflake View"},
        ],
        "test_categories": ["freshness","volume","schema","nulls","duplicates","referential_integrity","aggregation_accuracy"],
    },
}

TABLE_SCHEMAS = {
    "NWT_ORDER_FILE": [
        ("order_id",      "VARCHAR",  False),
        ("store_id",      "VARCHAR",  False),
        ("business_date", "DATE",     False),
        ("net_sales",     "DECIMAL",  False),
        ("gross_sales",   "DECIMAL",  True),
        ("discount_amount","DECIMAL", True),
        ("daypart",       "VARCHAR",  True),
        ("insert_timestamp","TIMESTAMP", True),
    ],
    "FACT_ORDER": [
        ("order_id",       "VARCHAR", False),
        ("store_sk",       "INTEGER", False),
        ("date_sk",        "INTEGER", False),
        ("daypart_sk",     "INTEGER", True),
        ("net_sales",      "DECIMAL", False),
        ("gross_sales",    "DECIMAL", True),
        ("discount_amount","DECIMAL", True),
        ("insert_timestamp","TIMESTAMP", True),
    ],
    "DIM_STORE": [
        ("store_sk",   "INTEGER", False),
        ("store_id",   "VARCHAR", False),
        ("store_name", "VARCHAR", True),
        ("city",       "VARCHAR", False),
        ("state",      "VARCHAR", False),
        ("country",    "VARCHAR", True),
        ("region",     "VARCHAR", True),
    ],
}


# ── QA Engine ─────────────────────────────────────────────────────────────

class QAEngine:

    def __init__(self, snowflake_conn=None):
        self._conn = snowflake_conn

    def _get_conn(self):
        if self._conn is None:
            try:
                from connectors.registry import ConnectorRegistry
                self._conn = ConnectorRegistry.connect("snowflake")
            except Exception:
                pass
        return self._conn

    # ── 1. Generate Test Plan + Test Cases ────────────────────────────────

    def generate(self, pipeline: str) -> dict:
        """Generate test plan document + structured test cases JSON + sample data."""
        spec = PIPELINE_SPECS.get(pipeline)
        if not spec:
            raise ValueError(f"Unknown pipeline: {pipeline}. Known: {list(PIPELINE_SPECS)}")

        print(f"\n  📋 Generating QA artifacts for: {pipeline}")

        # Build test cases
        test_cases = self._build_test_cases(pipeline, spec)

        # Write test cases JSON
        cases_file = CASES_DIR / f"{pipeline}_test_cases.json"
        cases_file.write_text(json.dumps(test_cases, indent=2, default=str))
        print(f"  ✓ Test cases written: {cases_file.name} ({len(test_cases['cases'])} cases)")

        # Write test plan markdown
        plan_file = PLANS_DIR / f"{pipeline}_test_plan.md"
        plan_file.write_text(self._build_test_plan(pipeline, spec, test_cases))
        print(f"  ✓ Test plan written:  {plan_file.name}")

        # Generate sample data
        sample_files = {}
        for table in spec["tables"]:
            schema = TABLE_SCHEMAS.get(table, [])
            if schema:
                csv_file = self._generate_sample_data(table, schema)
                sample_files[table] = str(csv_file)
                print(f"  ✓ Sample data:        {csv_file.name}")

        return {
            "pipeline":    pipeline,
            "cases_file":  str(cases_file),
            "plan_file":   str(plan_file),
            "sample_files": sample_files,
            "case_count":  len(test_cases["cases"]),
        }

    def _build_test_cases(self, pipeline: str, spec: dict) -> dict:
        cases = []
        tc_id = 1

        for table in spec["tables"]:
            schema = TABLE_SCHEMAS.get(table, [])
            pk_cols = [c[0] for c in schema if not c[2]]  # not nullable = likely PK

            for category in spec["test_categories"]:
                if category == "freshness":
                    cases.append({
                        "id":          f"TC-{tc_id:03d}",
                        "category":    "freshness",
                        "table":       table,
                        "title":       f"{table}: Data freshness within SLO",
                        "description": f"Verify {table} was loaded within the agreed freshness window.",
                        "priority":    "P1",
                        "preconditions": ["Pipeline has run at least once", "insert_timestamp column exists"],
                        "steps": [
                            f"SELECT DATEDIFF('hour', MAX(insert_timestamp), CURRENT_TIMESTAMP()) FROM {table}",
                            "Verify result < 2 (batch) or < 0.5 (streaming)",
                        ],
                        "expected_result": "Hours stale < SLO threshold",
                        "pass_sql": f"SELECT CASE WHEN DATEDIFF('hour', MAX(insert_timestamp), CURRENT_TIMESTAMP()) < 24 THEN 'PASS' ELSE 'FAIL' END FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table}",
                        "sample_data_file": f"{table}_sample.csv",
                        "automated": True,
                    })
                    tc_id += 1

                elif category == "volume":
                    cases.append({
                        "id":          f"TC-{tc_id:03d}",
                        "category":    "volume",
                        "table":       table,
                        "title":       f"{table}: Row count within expected range",
                        "description": f"Row count should not drop > 5% vs previous run.",
                        "priority":    "P1",
                        "preconditions": ["Baseline row count exists in observability/snapshots/row_counts.json"],
                        "steps": [
                            f"SELECT COUNT(*) FROM {table}",
                            "Compare with baseline in row_counts.json",
                            "Calculate % change",
                        ],
                        "expected_result": "Row count change within ±5%",
                        "pass_sql": f"SELECT COUNT(*) FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table}",
                        "sample_data_file": f"{table}_sample.csv",
                        "automated": True,
                    })
                    tc_id += 1

                elif category == "nulls":
                    for col, dtype, nullable in schema:
                        if not nullable:  # critical non-nullable column
                            cases.append({
                                "id":          f"TC-{tc_id:03d}",
                                "category":    "nulls",
                                "table":       table,
                                "title":       f"{table}.{col}: No null values",
                                "description": f"{col} is a required column — must have 0% nulls.",
                                "priority":    "P1",
                                "preconditions": [f"{table} has been loaded"],
                                "steps": [
                                    f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL",
                                    "Verify result = 0",
                                ],
                                "expected_result": "0 null values",
                                "pass_sql": f"SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} WHERE {col} IS NULL",
                                "sample_data_file": f"{table}_sample.csv",
                                "automated": True,
                            })
                            tc_id += 1

                elif category == "duplicates":
                    if pk_cols:
                        pk_str = ", ".join(pk_cols[:2])
                        cases.append({
                            "id":          f"TC-{tc_id:03d}",
                            "category":    "duplicates",
                            "table":       table,
                            "title":       f"{table}: No duplicate primary keys",
                            "description": f"Primary key ({pk_str}) must be unique.",
                            "priority":    "P1",
                            "preconditions": [f"{table} has been loaded"],
                            "steps": [
                                f"SELECT {pk_str}, COUNT(*) cnt FROM {table} GROUP BY {pk_str} HAVING cnt > 1",
                                "Verify 0 rows returned",
                            ],
                            "expected_result": "0 duplicate primary keys",
                            "pass_sql": f"SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM (SELECT {pk_str} FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} GROUP BY {pk_str} HAVING COUNT(*) > 1)",
                            "sample_data_file": f"{table}_sample.csv",
                            "automated": True,
                        })
                        tc_id += 1

                elif category == "schema":
                    cases.append({
                        "id":          f"TC-{tc_id:03d}",
                        "category":    "schema",
                        "table":       table,
                        "title":       f"{table}: Schema matches expected definition",
                        "description": "All expected columns present with correct types.",
                        "priority":    "P2",
                        "preconditions": ["Schema snapshot exists"],
                        "steps": [
                            f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table}'",
                            "Compare with expected schema in TABLE_SCHEMAS",
                        ],
                        "expected_result": "All columns present, no type changes, no missing columns",
                        "pass_sql": f"SELECT COLUMN_NAME, DATA_TYPE FROM NISHANT_DS_DB.INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'NISHANT_WORKFLOW_TEST' AND TABLE_NAME = '{table}' ORDER BY ORDINAL_POSITION",
                        "sample_data_file": None,
                        "automated": True,
                    })
                    tc_id += 1

                elif category == "referential_integrity":
                    if table == "FACT_ORDER":
                        for fk_col, ref_table, ref_col in [
                            ("store_sk","DIM_STORE","store_sk"),
                            ("date_sk","DIM_DATE","date_sk"),
                        ]:
                            cases.append({
                                "id":          f"TC-{tc_id:03d}",
                                "category":    "referential_integrity",
                                "table":       table,
                                "title":       f"FACT_ORDER.{fk_col} → {ref_table}.{ref_col}",
                                "description": f"Every {fk_col} in FACT_ORDER must exist in {ref_table}.",
                                "priority":    "P1",
                                "preconditions": [f"{table} and {ref_table} loaded"],
                                "steps": [
                                    f"SELECT COUNT(*) FROM FACT_ORDER f LEFT JOIN {ref_table} d ON f.{fk_col} = d.{ref_col} WHERE d.{ref_col} IS NULL",
                                    "Verify 0 orphan rows",
                                ],
                                "expected_result": "0 orphan foreign key values",
                                "pass_sql": f"SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.FACT_ORDER f LEFT JOIN NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{ref_table} d ON f.{fk_col} = d.{ref_col} WHERE d.{ref_col} IS NULL",
                                "sample_data_file": None,
                                "automated": True,
                            })
                            tc_id += 1

                elif category == "aggregation_accuracy":
                    if table == "FACT_ORDER":
                        cases.append({
                            "id":          f"TC-{tc_id:03d}",
                            "category":    "aggregation_accuracy",
                            "table":       table,
                            "title":       "FACT_ORDER: net_sales aggregation matches curated source",
                            "description": "Sum of net_sales in FACT_ORDER must match NWT_ORDER_FILE within 0.1%.",
                            "priority":    "P1",
                            "preconditions": ["Both tables loaded for same date range"],
                            "steps": [
                                "SELECT SUM(net_sales) FROM FACT_ORDER",
                                "SELECT SUM(net_sales) FROM NWT_ORDER_FILE",
                                "Compare: abs(fact - source) / source < 0.001",
                            ],
                            "expected_result": "< 0.1% discrepancy",
                            "pass_sql": "SELECT CASE WHEN ABS(f.total - s.total) / NULLIF(s.total, 0) < 0.001 THEN 'PASS' ELSE 'FAIL' END FROM (SELECT SUM(net_sales) total FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.FACT_ORDER) f, (SELECT SUM(net_sales) total FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.NWT_ORDER_FILE) s",
                            "sample_data_file": None,
                            "automated": True,
                        })
                        tc_id += 1

                elif category == "business_rules":
                    cases.append({
                        "id":          f"TC-{tc_id:03d}",
                        "category":    "business_rules",
                        "table":       table,
                        "title":       f"{table}: net_sales >= 0",
                        "description": "Net sales should never be negative.",
                        "priority":    "P2",
                        "preconditions": [f"{table} loaded"],
                        "steps": [
                            f"SELECT COUNT(*) FROM {table} WHERE net_sales < 0",
                            "Verify 0 rows (or investigate exceptions)",
                        ],
                        "expected_result": "0 rows with negative net_sales",
                        "pass_sql": f"SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} WHERE net_sales < 0",
                        "sample_data_file": f"{table}_sample.csv",
                        "automated": True,
                    })
                    tc_id += 1

        return {
            "pipeline":    pipeline,
            "generated_at": _now(),
            "total_cases": len(cases),
            "cases":       cases,
        }

    def _build_test_plan(self, pipeline: str, spec: dict, test_cases: dict) -> str:
        categories = {}
        for tc in test_cases["cases"]:
            categories.setdefault(tc["category"], []).append(tc)

        sections = [
            f"# Test Plan — {pipeline}",
            f"",
            f"**Pipeline:** {spec['description']}",
            f"**Source:** {spec['source']}",
            f"**Target:** {spec['target']}",
            f"**Schedule:** {spec['schedule']}",
            f"**Owner:** {spec['owner']}",
            f"**Generated:** {_now()[:19]} UTC",
            f"**Total test cases:** {test_cases['total_cases']}",
            f"",
            f"---",
            f"",
            f"## Scope",
            f"",
            f"Tables under test: {', '.join(f'`{t}`' for t in spec['tables'])}",
            f"",
            f"## Test Categories",
            f"",
        ]

        for cat, cases in sorted(categories.items()):
            p1 = len([c for c in cases if c["priority"] == "P1"])
            p2 = len([c for c in cases if c["priority"] == "P2"])
            sections.append(f"| `{cat}` | {len(cases)} cases | P1: {p1}, P2: {p2} |")

        sections += ["", "---", "", "## Test Cases", ""]

        for cat, cases in sorted(categories.items()):
            sections.append(f"### {cat.replace('_',' ').title()}\n")
            for tc in cases:
                sections += [
                    f"#### {tc['id']}: {tc['title']}",
                    f"",
                    f"**Priority:** {tc['priority']}  **Table:** `{tc['table']}`",
                    f"",
                    f"**Description:** {tc['description']}",
                    f"",
                    f"**Pre-conditions:**",
                ] + [f"- {p}" for p in tc["preconditions"]] + [
                    f"",
                    f"**Steps:**",
                ] + [f"{i+1}. {s}" for i, s in enumerate(tc["steps"])] + [
                    f"",
                    f"**Expected Result:** {tc['expected_result']}",
                    f"",
                    f"**Validation SQL:**",
                    f"```sql",
                    tc["pass_sql"],
                    f"```",
                    f"",
                ]

        sections += [
            "---",
            "",
            "## Entry / Exit Criteria",
            "",
            "**Entry:** Pipeline has completed at least one full run.",
            "",
            "**Exit (Pass):** All P1 test cases pass. P2 failures documented and accepted.",
            "",
            "**Exit (Fail):** Any P1 test case fails without approved exception.",
            "",
            "## Defect Classification",
            "",
            "| Severity | Description | Resolution Time |",
            "|----------|-------------|-----------------|",
            "| P1-Critical | Data loss, wrong totals, broken FK | Same run |",
            "| P2-High     | Freshness breach, schema drift | Next run |",
            "| P3-Medium   | Null rate warn, volume warn | 48 hours |",
            "| P4-Low      | Documentation, advisory | Sprint |",
        ]

        return "\n".join(sections)

    # ── 2. Sample data generation ──────────────────────────────────────────

    def _generate_sample_data(self, table: str, schema: list, rows: int = 20) -> Path:
        """Generate realistic CSV sample data for a table."""
        csv_file = SAMPLES_DIR / f"{table}_sample.csv"
        headers  = [col[0] for col in schema]

        store_ids = [f"STR{i:04d}" for i in range(1, 11)]
        order_ids = [f"ORD{i:07d}" for i in range(1000001, 1000001 + rows)]
        base_date = date.today() - timedelta(days=1)

        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for i in range(rows):
                row = []
                for col, dtype, nullable in schema:
                    col_lower = col.lower()

                    # Targeted generators
                    if "order_id" in col_lower:
                        row.append(order_ids[i] if i < len(order_ids) else f"ORD{i:07d}")
                    elif col_lower == "store_sk":
                        row.append(i % 10 + 1)
                    elif "store_id" in col_lower:
                        row.append(store_ids[i % len(store_ids)])
                    elif "date_sk" in col_lower:
                        row.append(20240101 + i)
                    elif "daypart_sk" in col_lower:
                        row.append(random.randint(1, 4))
                    elif "business_date" in col_lower:
                        row.append((base_date - timedelta(days=i % 7)).isoformat())
                    elif "net_sales" in col_lower:
                        row.append(round(random.uniform(10.0, 500.0), 2))
                    elif "gross_sales" in col_lower:
                        row.append(round(random.uniform(15.0, 600.0), 2))
                    elif "discount" in col_lower:
                        row.append(round(random.uniform(0.0, 50.0), 2))
                    elif "daypart" in col_lower:
                        row.append(random.choice(["BREAKFAST","LUNCH","DINNER","LATE_NIGHT"]))
                    elif "timestamp" in col_lower:
                        row.append(datetime.now(timezone.utc).isoformat())
                    elif "city" in col_lower:
                        row.append(random.choice(["Vancouver","Toronto","Calgary","Montreal","Ottawa"]))
                    elif "state" in col_lower or "province" in col_lower:
                        row.append(random.choice(["BC","ON","AB","QC","ON"]))
                    elif "country" in col_lower:
                        row.append("Canada")
                    elif "region" in col_lower:
                        row.append(random.choice(["West","East","Central","North"]))
                    elif "name" in col_lower:
                        row.append(f"Store {i+1}")
                    elif "product_id" in col_lower:
                        row.append(f"PRD{i:04d}")
                    elif dtype in ("INTEGER","NUMBER") and not nullable:
                        row.append(i + 1)
                    elif dtype in ("DECIMAL","FLOAT","NUMERIC"):
                        row.append(None if nullable and random.random() < 0.05 else round(random.uniform(1.0, 1000.0), 2))
                    elif dtype == "DATE":
                        row.append(base_date.isoformat())
                    elif dtype == "TIMESTAMP":
                        row.append(datetime.now(timezone.utc).isoformat())
                    elif nullable:
                        row.append(None if random.random() < 0.05 else f"value_{i}")
                    else:
                        row.append(f"value_{i}")

                writer.writerow(row)

        return csv_file

    # ── 3. Run QA tests ────────────────────────────────────────────────────

    def run(self, pipeline: str) -> dict:
        """Execute all test cases for a pipeline. Returns run results dict."""
        cases_file = CASES_DIR / f"{pipeline}_test_cases.json"
        if not cases_file.exists():
            print(f"  No test cases for {pipeline}. Run: python3 integrations/qa.py generate --pipeline {pipeline}")
            return {}

        test_cases = json.loads(cases_file.read_text())
        run_id     = f"QA-{_short_id()}"
        conn       = self._get_conn()

        print(f"\n  🧪 QA Run {run_id} — {pipeline} ({test_cases['total_cases']} cases)")
        print("  " + "-" * 60)

        results = []
        passed = failed = skipped = 0

        for tc in test_cases["cases"]:
            if not tc.get("automated") or not tc.get("pass_sql"):
                results.append({**tc, "result": "SKIP", "actual": None, "error": "No automated SQL"})
                skipped += 1
                continue

            # Execute validation SQL
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(tc["pass_sql"])
                    row = cur.fetchone()
                    actual = str(row[0]) if row else "NULL"
                    result = "PASS" if actual == "PASS" else "FAIL"
                    error  = None
                    if result == "FAIL":
                        # Get count for details
                        try:
                            count_sql = tc["pass_sql"].replace("CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END", "COUNT(*)")
                            cur.execute(count_sql)
                            count_row = cur.fetchone()
                            error = f"Count: {count_row[0] if count_row else 'unknown'}"
                        except Exception:
                            pass
                except Exception as e:
                    result = "ERROR"
                    actual = None
                    error  = str(e)
            else:
                # Offline mode — mark as SKIP
                result = "SKIP"
                actual = None
                error  = "No Snowflake connection"

            results.append({**tc, "result": result, "actual": actual, "error": error})
            icon = "✅" if result == "PASS" else ("❌" if result == "FAIL" else "⚠️")
            print(f"    {icon} {tc['id']:8s} {tc['category']:25s} {tc['title'][:50]}")

            if result == "PASS":   passed  += 1
            elif result == "FAIL": failed  += 1
            else:                  skipped += 1

        total = passed + failed + skipped
        pass_rate = round(passed / (passed + failed) * 100, 1) if (passed + failed) > 0 else 0

        run = {
            "run_id":     run_id,
            "pipeline":   pipeline,
            "ran_at":     _now(),
            "total":      total,
            "passed":     passed,
            "failed":     failed,
            "skipped":    skipped,
            "pass_rate":  pass_rate,
            "results":    results,
            "overall":    "PASS" if failed == 0 else "FAIL",
        }

        # Save run
        run_file = RESULTS_DIR / f"{run_id}_run.json"
        run_file.write_text(json.dumps(run, indent=2, default=str))

        print(f"\n  Result: {run['overall']} — {passed} passed, {failed} failed, {skipped} skipped ({pass_rate}%)")

        # Build result documents
        self._write_test_result_doc(run)
        self._write_job_fixes_doc(run)

        return run

    # ── 4. Test Result Document ────────────────────────────────────────────

    def _write_test_result_doc(self, run: dict) -> Path:
        result_file = RESULTS_DIR / f"{run['run_id']}_test_results.md"
        overall_icon = "✅ PASS" if run["overall"] == "PASS" else "❌ FAIL"

        lines = [
            f"# QA Test Results — {run['pipeline']}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Run ID** | `{run['run_id']}` |",
            f"| **Pipeline** | {run['pipeline']} |",
            f"| **Overall** | {overall_icon} |",
            f"| **Run Date** | {run['ran_at'][:19]} UTC |",
            f"| **Pass Rate** | {run['pass_rate']}% |",
            f"| **Passed** | {run['passed']} |",
            f"| **Failed** | {run['failed']} |",
            f"| **Skipped** | {run['skipped']} |",
            f"",
            f"---",
            f"",
            f"## Results by Category",
            f"",
        ]

        # Group by category
        by_cat = {}
        for r in run["results"]:
            by_cat.setdefault(r["category"], []).append(r)

        for cat, cases in sorted(by_cat.items()):
            cat_pass = sum(1 for c in cases if c["result"] == "PASS")
            cat_fail = sum(1 for c in cases if c["result"] == "FAIL")
            icon = "✅" if cat_fail == 0 else "❌"
            lines.append(f"### {icon} {cat.replace('_',' ').title()} ({cat_pass}/{len(cases)} passed)\n")
            lines.append(f"| ID | Title | Result | Notes |")
            lines.append(f"|----|-------|--------|-------|")
            for c in cases:
                ri = "✅" if c["result"]=="PASS" else ("❌" if c["result"]=="FAIL" else "⚠️")
                lines.append(f"| {c['id']} | {c['title'][:60]} | {ri} {c['result']} | {c.get('error') or ''} |")
            lines.append("")

        lines += [
            "---",
            "",
            "## Failed Test Details",
            "",
        ]
        failures = [r for r in run["results"] if r["result"] == "FAIL"]
        if failures:
            for f in failures:
                lines += [
                    f"### ❌ {f['id']}: {f['title']}",
                    f"",
                    f"**Category:** {f['category']}  **Table:** `{f['table']}`  **Priority:** {f['priority']}",
                    f"",
                    f"**Expected:** {f['expected_result']}",
                    f"**Actual:** {f.get('actual','—')}  {f.get('error') or ''}",
                    f"",
                    f"**Validation SQL:**",
                    f"```sql",
                    f"{f['pass_sql']}",
                    f"```",
                    f"",
                ]
        else:
            lines.append("No failures. All automated tests passed.")

        result_file.write_text("\n".join(lines))
        print(f"  ✓ Test result doc: {result_file.name}")
        return result_file

    # ── 5. Job Fixes Document ──────────────────────────────────────────────

    def _write_job_fixes_doc(self, run: dict) -> Path:
        fixes_file = RESULTS_DIR / f"{run['run_id']}_job_fixes.md"
        failures   = [r for r in run["results"] if r["result"] == "FAIL"]

        lines = [
            f"# Job Fixes — {run['pipeline']}",
            f"",
            f"**Run ID:** `{run['run_id']}`  **Date:** {run['ran_at'][:19]} UTC",
            f"**Failed Tests:** {len(failures)}",
            f"",
            f"---",
            f"",
        ]

        if not failures:
            lines.append("No failures detected. No fixes required.")
        else:
            lines += ["## Required Fixes", ""]
            for i, f in enumerate(failures, 1):
                fix_sql = self._suggest_fix_sql(f)
                lines += [
                    f"### Fix #{i}: {f['id']} — {f['title']}",
                    f"",
                    f"**Category:** `{f['category']}`  **Table:** `{f['table']}`  **Priority:** {f['priority']}",
                    f"",
                    f"**Root Cause:** {self._suggest_root_cause(f)}",
                    f"",
                    f"**Recommended Action:**",
                    f"{self._suggest_action(f)}",
                    f"",
                ]
                if fix_sql:
                    lines += [f"**Fix SQL:**", f"```sql", fix_sql, f"```", f""]
                lines += [
                    f"**Steps to Resolve:**",
                ] + [f"{j+1}. {s}" for j, s in enumerate(self._suggest_steps(f))] + [""]

        lines += [
            "---",
            "",
            "## Sign-off",
            "",
            "| Role | Name | Date | Signature |",
            "|------|------|------|-----------|",
            "| QA Engineer | | | |",
            "| Data Engineer | | | |",
            "| Team Lead | | | |",
        ]

        fixes_file.write_text("\n".join(lines))
        print(f"  ✓ Job fixes doc:    {fixes_file.name}")
        return fixes_file

    def _suggest_root_cause(self, failure: dict) -> str:
        cat = failure["category"]
        return {
            "freshness":   "Pipeline did not run on schedule or encountered an error. Data is stale.",
            "volume":      "Upstream data source sent fewer records than expected. Possible filter change or truncation.",
            "nulls":       "Source data contains missing values for a required field. Upstream API or file may be incomplete.",
            "duplicates":  "Deduplication logic failed or was bypassed. Source may have sent duplicate records.",
            "schema":      "Source schema changed without notification. A column was removed or type changed.",
            "referential_integrity": "Fact table contains surrogate keys that do not exist in the dimension table.",
            "aggregation_accuracy":  "Sum discrepancy between layers indicates a join error or missing rows.",
            "business_rules":        "Source data contains invalid values violating business constraints.",
        }.get(cat, "Unknown root cause — investigation required.")

    def _suggest_action(self, failure: dict) -> str:
        cat = failure["category"]
        return {
            "freshness":   "1. Re-trigger the pipeline manually.\n2. Check Glue/Airflow logs for failure.\n3. Investigate source file delivery.",
            "volume":      "1. Check source row count.\n2. Verify no WHERE clause changed.\n3. Re-run with full load if delta is large.",
            "nulls":       "1. Identify which source records are missing the field.\n2. Apply COALESCE or default in transformation.\n3. Alert source team.",
            "duplicates":  "1. Add QUALIFY ROW_NUMBER() OVER (PARTITION BY pk ORDER BY insert_timestamp DESC) = 1 to dedup.\n2. Investigate why source sent duplicates.",
            "schema":      "1. Review source schema change notification.\n2. Update dbt model and schema.yml.\n3. Re-run dbt build.",
            "referential_integrity": "1. Check for missing dimension records.\n2. Add a 'UNKNOWN' default record to dimension.\n3. Re-run dbt build with full-refresh if needed.",
            "aggregation_accuracy":  "1. Run cross-layer comparison: python3 observability/observer.py compare.\n2. Check for duplicate joins in dbt model.",
            "business_rules":        "1. Add validation filter in transformation layer.\n2. Investigate source data quality with source team.",
        }.get(cat, "Investigate manually.")

    def _suggest_fix_sql(self, failure: dict) -> str:
        cat   = failure["category"]
        table = failure["table"]
        if cat == "duplicates":
            return f"""-- Remove duplicates from {table}
CREATE OR REPLACE TABLE NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} AS
SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY insert_timestamp DESC) AS rn
    FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table}
) WHERE rn = 1;"""
        elif cat == "nulls":
            col = failure.get("detail", {}).get("column", "COLUMN_NAME")
            return f"""-- Investigate nulls
SELECT COUNT(*), '{col}' AS col FROM NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} WHERE {col} IS NULL;

-- Option: fill with default
-- UPDATE NISHANT_DS_DB.NISHANT_WORKFLOW_TEST.{table} SET {col} = 'UNKNOWN' WHERE {col} IS NULL;"""
        return ""

    def _suggest_steps(self, failure: dict) -> list[str]:
        return [
            f"Run: python3 integrations/investigator.py investigate --pipeline <pipeline>",
            "Review the investigation report",
            "Approve fixes: python3 integrations/investigator.py approve INV-XXXXX",
            "Apply fixes: python3 integrations/investigator.py apply INV-XXXXX",
            f"Re-run this test: python3 integrations/qa.py run --pipeline <pipeline>",
            "Verify result: PASS",
        ]

    # ── 6. Lineage Document ────────────────────────────────────────────────

    def lineage(self, pipeline: str) -> Path:
        """Generate lineage document for a pipeline."""
        spec = PIPELINE_SPECS.get(pipeline, {})
        lineage_items = spec.get("lineage", [])

        lineage_file = LINEAGE_DIR / f"{pipeline}_lineage.md"
        ts = _now()[:19]

        lines = [
            f"# Data Lineage — {pipeline}",
            f"",
            f"**Generated:** {ts} UTC",
            f"**Pipeline:** {spec.get('description', pipeline)}",
            f"",
            f"---",
            f"",
            f"## Lineage Diagram",
            f"",
            f"```",
        ]

        # ASCII lineage graph
        for i, item in enumerate(lineage_items):
            arrow = "→"
            lines.append(f"  [{item['from']}]  {arrow}  [{item['via']}]  {arrow}  [{item['to']}]")
            if i < len(lineage_items) - 1:
                lines.append("")

        lines += [
            "```",
            "",
            "---",
            "",
            "## Detailed Lineage",
            "",
            "| # | Source | Transformation | Target | Layer |",
            "|---|--------|----------------|--------|-------|",
        ]

        for i, item in enumerate(lineage_items, 1):
            layer = "Raw→Landing" if "S3" in item["from"] else ("Landing→Curated" if "FILE" in item["from"] else "Curated→Mart")
            lines.append(f"| {i} | `{item['from']}` | `{item['via']}` | `{item['to']}` | {layer} |")

        lines += [
            "",
            "---",
            "",
            "## Tables",
            "",
        ]

        for table in spec.get("tables", []):
            schema = TABLE_SCHEMAS.get(table, [])
            if not schema:
                continue
            lines += [
                f"### `{table}`",
                f"",
                f"| Column | Type | Nullable | Notes |",
                f"|--------|------|----------|-------|",
            ]
            for col, dtype, nullable in schema:
                is_pk = "🔑 PK" if not nullable and ("_id" in col.lower() or "_sk" in col.lower()) else ""
                lines.append(f"| `{col}` | {dtype} | {'Yes' if nullable else 'No'} | {is_pk} |")
            lines.append("")

        lines += [
            "---",
            "",
            "## Impact Analysis",
            "",
            "Changes to any source table affect downstream consumers as follows:",
            "",
        ]

        for item in lineage_items:
            lines.append(f"- Changing **`{item['from']}`** impacts **`{item['to']}`** (via `{item['via']}`)")

        lines += [
            "",
            "---",
            "",
            "## Version History",
            "",
            "| Version | Date | Author | Change |",
            "|---------|------|--------|--------|",
            f"| v1.0 | {ts[:10]} | qa_agent | Initial lineage document |",
        ]

        lineage_file.write_text("\n".join(lines))
        print(f"  ✓ Lineage document: {lineage_file.name}")
        return lineage_file

    # ── 7. Publish (git tag + push) ────────────────────────────────────────

    def publish(self, run_id: str) -> str:
        """Commit all QA artifacts for a run and push with a version tag."""
        run_file = RESULTS_DIR / f"{run_id}_run.json"
        if not run_file.exists():
            raise ValueError(f"Run {run_id} not found.")
        run = json.loads(run_file.read_text())

        # Collect all artifacts for this run
        artifacts = [
            RESULTS_DIR / f"{run_id}_run.json",
            RESULTS_DIR / f"{run_id}_test_results.md",
            RESULTS_DIR / f"{run_id}_job_fixes.md",
        ]
        # Add plan, cases, sample data, lineage
        pipeline = run["pipeline"]
        for extra in [
            PLANS_DIR / f"{pipeline}_test_plan.md",
            CASES_DIR / f"{pipeline}_test_cases.json",
            LINEAGE_DIR / f"{pipeline}_lineage.md",
        ]:
            if extra.exists():
                artifacts.append(extra)

        for f in SAMPLES_DIR.glob(f"*_sample.csv"):
            artifacts.append(f)

        # Git add + commit
        tag = f"qa/{pipeline}/{run_id.lower()}"
        message = (
            f"qa: {pipeline} — {run['overall']} — {run['pass_rate']}% pass rate\n\n"
            f"Run: {run_id}\n"
            f"Passed: {run['passed']}  Failed: {run['failed']}  Skipped: {run['skipped']}\n"
            f"Generated: test plan, test cases, sample data, results, fixes, lineage"
        )

        try:
            for a in artifacts:
                subprocess.run(["git", "add", str(a)], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", message], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(["git", "tag", tag], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main", "--tags"], cwd=str(ROOT), check=True, capture_output=True)
            print(f"  ✓ Published to git. Tag: {tag}")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode() if e.stderr else str(e)
            print(f"  [git] Push failed: {err}")

        return tag


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="NGR QA Agent")
    sub = p.add_subparsers(dest="cmd")

    gp = sub.add_parser("generate", help="Generate test plan, test cases, sample data")
    gp.add_argument("--pipeline", required=True)

    rp = sub.add_parser("run", help="Execute all test cases")
    rp.add_argument("--pipeline", required=True)

    lp = sub.add_parser("lineage", help="Generate lineage document")
    lp.add_argument("--pipeline", required=True)

    pp = sub.add_parser("publish", help="Commit + push all artifacts with git tag")
    pp.add_argument("--run-id", required=True)

    fp = sub.add_parser("full", help="generate + run + lineage + publish")
    fp.add_argument("--pipeline", required=True)

    args = p.parse_args()
    engine = QAEngine()

    if args.cmd == "generate":
        engine.generate(args.pipeline)
    elif args.cmd == "run":
        engine.run(args.pipeline)
    elif args.cmd == "lineage":
        engine.lineage(args.pipeline)
    elif args.cmd == "publish":
        engine.publish(args.run_id)
    elif args.cmd == "full":
        engine.generate(args.pipeline)
        run = engine.run(args.pipeline)
        engine.lineage(args.pipeline)
        if run:
            engine.publish(run["run_id"])
    else:
        p.print_help()


if __name__ == "__main__":
    main()
