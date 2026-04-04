#!/usr/bin/env python3
"""
integrations/investigator.py — Pipeline Investigation Engine

Investigates:
  - Job failures (Glue, Airflow, dbt, Spark)
  - Schema drift (column added/removed/type changed)
  - Data drift (statistical distribution shift)
  - Data freshness violations
  - Null rate anomalies
  - Volume anomalies

Flow:
  1. run_investigation(pipeline)   → builds Investigation report
  2. Human reads report, approves or rejects
  3. apply_fixes(investigation_id) → applies approved fixes + pushes to git

Usage:
  python3 integrations/investigator.py investigate --pipeline nwt_batch_load
  python3 integrations/investigator.py list
  python3 integrations/investigator.py show INV-ABC123
  python3 integrations/investigator.py approve INV-ABC123 --notes "Looks good, apply fix"
  python3 integrations/investigator.py reject  INV-ABC123 --notes "Need more context"
  python3 integrations/investigator.py apply   INV-ABC123
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

INVESTIGATIONS_DIR = ROOT / "investigations"
INVESTIGATIONS_DIR.mkdir(parents=True, exist_ok=True)

FIXES_DIR = ROOT / "investigations" / "fixes"
FIXES_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:6].upper()


# ── Check runners ─────────────────────────────────────────────────────────

class InvestigationEngine:
    """
    Runs a full investigation on a pipeline or table and produces a structured
    report with findings, root cause analysis, and proposed fixes.
    """

    def __init__(self, snowflake_conn=None, alert_engine=None):
        self._conn   = snowflake_conn
        self._alerts = alert_engine

    def _get_conn(self):
        if self._conn is None:
            try:
                from connectors.registry import ConnectorRegistry
                self._conn = ConnectorRegistry.connect("snowflake")
            except Exception as e:
                print(f"  [Investigator] Could not connect to Snowflake: {e}")
        return self._conn

    def _get_alerts(self):
        if self._alerts is None:
            from integrations.alerts import AlertEngine
            self._alerts = AlertEngine()
        return self._alerts

    # ── Main investigation entry ───────────────────────────────────────────

    def run_investigation(
        self,
        pipeline:    str,
        tables:      list[str] = None,
        database:    str = "NISHANT_DS_DB",
        schema:      str = "NISHANT_WORKFLOW_TEST",
        auto_alert:  bool = True,
    ) -> dict:
        """
        Run full investigation on a pipeline.
        Returns investigation dict with all findings and proposed fixes.
        """
        inv_id = f"INV-{_short_id()}"
        print(f"\n  🔍 Investigation {inv_id} — pipeline: {pipeline}")
        print("  " + "-" * 60)

        findings = []

        # 1. Job failure check (Glue / Airflow / dbt)
        job_findings = self._check_job_failures(pipeline)
        findings.extend(job_findings)

        # 2. Schema drift
        schema_findings = self._check_schema_drift(tables or [], database, schema)
        findings.extend(schema_findings)

        # 3. Data drift (distribution)
        drift_findings = self._check_data_drift(tables or [], database, schema)
        findings.extend(drift_findings)

        # 4. Freshness
        freshness_findings = self._check_freshness(tables or [], database, schema)
        findings.extend(freshness_findings)

        # 5. Null checks
        null_findings = self._check_nulls(tables or [], database, schema)
        findings.extend(null_findings)

        # 6. Volume anomaly
        volume_findings = self._check_volume(tables or [], database, schema)
        findings.extend(volume_findings)

        # Score severity
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        high     = [f for f in findings if f["severity"] == "HIGH"]
        medium   = [f for f in findings if f["severity"] == "MEDIUM"]

        overall = "CRITICAL" if critical else ("HIGH" if high else ("MEDIUM" if medium else "HEALTHY"))

        # Build proposed fixes
        fixes = self._propose_fixes(findings)

        investigation = {
            "id":             inv_id,
            "pipeline":       pipeline,
            "tables":         tables or [],
            "status":         "PENDING_REVIEW",   # → APPROVED / REJECTED / APPLIED
            "overall":        overall,
            "findings":       findings,
            "fixes":          fixes,
            "summary":        self._build_summary(findings, fixes),
            "investigated_at": _now(),
            "approved_at":    None,
            "approved_by":    None,
            "applied_at":     None,
            "human_notes":    "",
            "git_commit":     "",
        }

        # Save
        inv_file = INVESTIGATIONS_DIR / f"{inv_id}.json"
        inv_file.write_text(json.dumps(investigation, indent=2, default=str))

        # Print report to console
        self._print_report(investigation)

        # Alert if high/critical findings
        if auto_alert and overall in ("CRITICAL", "HIGH"):
            self._send_alert(investigation)

        return investigation

    # ── Individual checks ──────────────────────────────────────────────────

    def _check_job_failures(self, pipeline: str) -> list[dict]:
        """Check Glue job run status, dbt test results, Airflow last run."""
        findings = []

        # Glue job check
        try:
            import boto3
            glue = boto3.client("glue", region_name=os.environ.get("AWS_DEFAULT_REGION","us-east-1"))
            runs = glue.get_job_runs(JobName=pipeline, MaxResults=5).get("JobRuns", [])
            failed = [r for r in runs if r.get("JobRunState") == "FAILED"]
            if failed:
                last = failed[0]
                findings.append({
                    "check":       "job_failure",
                    "severity":    "CRITICAL",
                    "table":       pipeline,
                    "finding":     f"Glue job '{pipeline}' failed: {last.get('ErrorMessage','unknown error')}",
                    "detail":      {
                        "run_id":   last.get("Id"),
                        "started":  str(last.get("StartedOn","")),
                        "error":    last.get("ErrorMessage",""),
                    },
                    "fix_type":    "glue_job_retry",
                    "fix_action":  f"aws glue start-job-run --job-name {pipeline}",
                    "fix_code":    None,
                })
        except Exception as e:
            findings.append({
                "check":    "job_failure",
                "severity": "LOW",
                "table":    pipeline,
                "finding":  f"Could not check Glue job status: {e}",
                "detail":   {},
                "fix_type": None,
                "fix_action": None,
                "fix_code": None,
            })

        # dbt test results
        dbt_dir = ROOT / "dbt"
        if dbt_dir.exists():
            try:
                result = subprocess.run(
                    ["dbt", "test", "--select", pipeline, "--output", "json"],
                    capture_output=True, text=True, cwd=str(dbt_dir), timeout=120,
                )
                if result.returncode != 0:
                    # Parse failures from output
                    for line in result.stdout.splitlines():
                        if '"status": "fail"' in line:
                            try:
                                rec = json.loads(line)
                                findings.append({
                                    "check":     "dbt_test_failure",
                                    "severity":  "HIGH",
                                    "table":     rec.get("node_name","unknown"),
                                    "finding":   f"dbt test failed: {rec.get('node_name')}",
                                    "detail":    rec,
                                    "fix_type":  "dbt_test",
                                    "fix_action":"dbt test --select " + rec.get("node_name",""),
                                    "fix_code":  None,
                                })
                            except Exception:
                                pass
            except Exception:
                pass

        return findings

    def _check_schema_drift(self, tables: list[str], database: str, schema: str) -> list[dict]:
        """Compare current schema vs saved snapshot. Detect added/removed/type-changed columns."""
        findings = []
        conn = self._get_conn()
        if not conn:
            return findings

        snapshot_dir = ROOT / "observability" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        for table in tables:
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
                    FROM {database}.INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'
                    ORDER BY ORDINAL_POSITION
                """)
                current = {r[0]: {"type": r[1], "nullable": r[2], "length": r[3]} for r in cur.fetchall()}

                snapshot_file = snapshot_dir / f"schema_{table}.json"
                if not snapshot_file.exists():
                    # First run — save baseline
                    snapshot_file.write_text(json.dumps(current, indent=2))
                    continue

                previous = json.loads(snapshot_file.read_text())

                # Removed columns
                removed = [c for c in previous if c not in current]
                # Added columns
                added   = [c for c in current if c not in previous]
                # Type changes
                changed = [
                    c for c in current
                    if c in previous and current[c]["type"] != previous[c]["type"]
                ]

                if removed:
                    findings.append({
                        "check":     "schema_drift",
                        "severity":  "CRITICAL",
                        "table":     table,
                        "finding":   f"Columns REMOVED from {table}: {removed}",
                        "detail":    {"removed": removed, "previous_types": {c: previous[c] for c in removed}},
                        "fix_type":  "schema_restore",
                        "fix_action":f"ALTER TABLE {schema}.{table} ADD COLUMN ...",
                        "fix_code":  self._gen_add_columns_sql(schema, table, removed, previous),
                    })

                if changed:
                    findings.append({
                        "check":     "schema_drift",
                        "severity":  "HIGH",
                        "table":     table,
                        "finding":   f"Column type changed in {table}: {changed}",
                        "detail":    {
                            c: {"from": previous[c]["type"], "to": current[c]["type"]}
                            for c in changed
                        },
                        "fix_type":  "schema_type_change",
                        "fix_action": "Review dbt model and source for type mismatch",
                        "fix_code":  None,
                    })

                if added:
                    findings.append({
                        "check":    "schema_drift",
                        "severity": "LOW",
                        "table":    table,
                        "finding":  f"New columns in {table}: {added}",
                        "detail":   {"added": added},
                        "fix_type": "schema_new_columns",
                        "fix_action":"Update dbt model schema.yml to document new columns",
                        "fix_code": self._gen_schema_yml_columns(added, current),
                    })

                # Update snapshot
                snapshot_file.write_text(json.dumps(current, indent=2))

            except Exception as e:
                findings.append({
                    "check":    "schema_drift",
                    "severity": "LOW",
                    "table":    table,
                    "finding":  f"Schema drift check error on {table}: {e}",
                    "detail":   {"error": str(e)},
                    "fix_type": None, "fix_action": None, "fix_code": None,
                })

        return findings

    def _check_data_drift(self, tables: list[str], database: str, schema: str) -> list[dict]:
        """Statistical distribution drift using z-score on key numeric columns."""
        findings = []
        conn = self._get_conn()
        if not conn:
            return findings

        baseline_file = ROOT / "observability" / "snapshots" / "data_drift_baseline.json"
        baseline = json.loads(baseline_file.read_text()) if baseline_file.exists() else {}

        for table in tables:
            try:
                cur = conn.cursor()
                # Get numeric column stats for today vs baseline
                cur.execute(f"""
                    SELECT COLUMN_NAME
                    FROM {database}.INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = '{schema}'
                      AND TABLE_NAME   = '{table}'
                      AND DATA_TYPE IN ('NUMBER','FLOAT','INTEGER','DECIMAL','NUMERIC','DOUBLE')
                    LIMIT 10
                """)
                numeric_cols = [r[0] for r in cur.fetchall()]

                for col in numeric_cols:
                    cur.execute(f"""
                        SELECT
                            AVG({col})    AS mean,
                            STDDEV({col}) AS stddev,
                            MIN({col})    AS min_val,
                            MAX({col})    AS max_val,
                            COUNT({col})  AS cnt
                        FROM {database}.{schema}.{table}
                    """)
                    row = cur.fetchone()
                    if not row or row[0] is None:
                        continue

                    current_mean   = float(row[0])
                    current_stddev = float(row[1] or 0)
                    key = f"{table}.{col}"

                    if key in baseline:
                        prev_mean   = baseline[key]["mean"]
                        prev_stddev = baseline[key]["stddev"] or 1
                        z = abs(current_mean - prev_mean) / prev_stddev

                        if z > 3:
                            findings.append({
                                "check":    "data_drift",
                                "severity": "HIGH",
                                "table":    table,
                                "finding":  f"Data drift on {table}.{col}: z-score={z:.2f} (current mean={current_mean:.2f}, baseline mean={prev_mean:.2f})",
                                "detail":   {
                                    "column":          col,
                                    "current_mean":    current_mean,
                                    "baseline_mean":   prev_mean,
                                    "z_score":         round(z, 3),
                                    "current_stddev":  current_stddev,
                                },
                                "fix_type":   "data_drift_investigation",
                                "fix_action": f"Investigate source data changes for {table}.{col}",
                                "fix_code":   None,
                            })
                        elif z > 2:
                            findings.append({
                                "check":    "data_drift",
                                "severity": "MEDIUM",
                                "table":    table,
                                "finding":  f"Data drift WARNING on {table}.{col}: z-score={z:.2f}",
                                "detail":   {"column": col, "z_score": round(z, 3)},
                                "fix_type": None, "fix_action": None, "fix_code": None,
                            })

                    # Update baseline
                    baseline[key] = {
                        "mean":   current_mean,
                        "stddev": current_stddev,
                        "updated": _now(),
                    }

            except Exception as e:
                pass

        baseline_file.write_text(json.dumps(baseline, indent=2, default=str))
        return findings

    def _check_freshness(self, tables: list[str], database: str, schema: str) -> list[dict]:
        """Check insert_timestamp freshness per table."""
        findings = []
        conn = self._get_conn()
        if not conn:
            return findings

        freshness_thresholds = {
            "NWT_ORDER_FILE":        {"warn": 2,  "fail": 24},
            "NWT_ORDER_PRODUCT_FILE":{"warn": 2,  "fail": 24},
            "FACT_ORDER":            {"warn": 3,  "fail": 24},
            "DIM_STORE":             {"warn": 24, "fail": 72},
        }

        for table in tables:
            thresholds = freshness_thresholds.get(table, {"warn": 2, "fail": 24})
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT DATEDIFF('hour', MAX(insert_timestamp), CURRENT_TIMESTAMP())
                    FROM {database}.{schema}.{table}
                """)
                row = cur.fetchone()
                if not row or row[0] is None:
                    findings.append({
                        "check":    "freshness",
                        "severity": "CRITICAL",
                        "table":    table,
                        "finding":  f"{table}: no insert_timestamp found — table may be empty",
                        "detail":   {},
                        "fix_type": "freshness_empty_table",
                        "fix_action": f"Trigger pipeline reload for {table}",
                        "fix_code": None,
                    })
                    continue

                hours_stale = float(row[0])
                if hours_stale >= thresholds["fail"]:
                    findings.append({
                        "check":    "freshness",
                        "severity": "CRITICAL",
                        "table":    table,
                        "finding":  f"{table}: data is {hours_stale:.1f}h stale (SLO: {thresholds['fail']}h)",
                        "detail":   {"hours_stale": hours_stale, "threshold_fail": thresholds["fail"]},
                        "fix_type": "freshness_pipeline_reload",
                        "fix_action": f"Re-trigger pipeline for {table}",
                        "fix_code": None,
                    })
                elif hours_stale >= thresholds["warn"]:
                    findings.append({
                        "check":    "freshness",
                        "severity": "MEDIUM",
                        "table":    table,
                        "finding":  f"{table}: data is {hours_stale:.1f}h stale (warn: {thresholds['warn']}h)",
                        "detail":   {"hours_stale": hours_stale},
                        "fix_type": None, "fix_action": None, "fix_code": None,
                    })
            except Exception as e:
                pass

        return findings

    def _check_nulls(self, tables: list[str], database: str, schema: str) -> list[dict]:
        """Check null rates on critical columns."""
        findings = []
        conn = self._get_conn()
        if not conn:
            return findings

        critical_columns = {
            "NWT_ORDER_FILE":        ["order_id","store_id","business_date","net_sales"],
            "NWT_ORDER_PRODUCT_FILE":["order_id","product_id"],
            "FACT_ORDER":            ["order_id","store_sk","date_sk","net_sales"],
            "DIM_STORE":             ["store_sk","store_id","city","state"],
        }

        for table in tables:
            cols = critical_columns.get(table, [])
            for col in cols:
                try:
                    cur = conn.cursor()
                    cur.execute(f"""
                        SELECT
                            COUNT(*) AS total,
                            SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_count
                        FROM {database}.{schema}.{table}
                    """)
                    row = cur.fetchone()
                    if not row or row[0] == 0:
                        continue
                    null_pct = (row[1] / row[0]) * 100
                    if null_pct > 5:
                        findings.append({
                            "check":    "nulls",
                            "severity": "HIGH" if null_pct > 20 else "MEDIUM",
                            "table":    table,
                            "finding":  f"{table}.{col}: {null_pct:.1f}% null ({row[1]:,} of {row[0]:,} rows)",
                            "detail":   {"column": col, "null_pct": round(null_pct,2), "null_count": row[1], "total": row[0]},
                            "fix_type": "null_investigation",
                            "fix_action": f"Investigate source for missing {col} values in {table}",
                            "fix_code": self._gen_null_fix_sql(schema, table, col),
                        })
                except Exception:
                    pass

        return findings

    def _check_volume(self, tables: list[str], database: str, schema: str) -> list[dict]:
        """Check row count vs baseline."""
        findings = []
        conn = self._get_conn()
        if not conn:
            return findings

        baseline_file = ROOT / "observability" / "snapshots" / "row_counts.json"
        baseline = json.loads(baseline_file.read_text()) if baseline_file.exists() else {}

        for table in tables:
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {database}.{schema}.{table}")
                current = cur.fetchone()[0]

                if table in baseline:
                    prev = baseline[table]["count"]
                    if prev > 0:
                        drop_pct = ((prev - current) / prev) * 100
                        if drop_pct > 20:
                            findings.append({
                                "check":    "volume",
                                "severity": "CRITICAL",
                                "table":    table,
                                "finding":  f"{table}: row count dropped {drop_pct:.1f}% ({prev:,} → {current:,})",
                                "detail":   {"previous": prev, "current": current, "drop_pct": round(drop_pct,2)},
                                "fix_type": "volume_pipeline_reload",
                                "fix_action": f"Re-run pipeline for {table}, check for accidental DELETE or truncation",
                                "fix_code": None,
                            })
                        elif drop_pct > 5:
                            findings.append({
                                "check":    "volume",
                                "severity": "MEDIUM",
                                "table":    table,
                                "finding":  f"{table}: row count dropped {drop_pct:.1f}% (warn threshold)",
                                "detail":   {"previous": prev, "current": current, "drop_pct": round(drop_pct,2)},
                                "fix_type": None, "fix_action": None, "fix_code": None,
                            })

                baseline[table] = {"count": current, "updated": _now()}

            except Exception:
                pass

        baseline_file.write_text(json.dumps(baseline, indent=2, default=str))
        return findings

    # ── Fix application ────────────────────────────────────────────────────

    def approve(self, inv_id: str, notes: str = "", approved_by: str = "human") -> dict:
        """Human approval — marks investigation as approved, ready to apply."""
        inv = self._load(inv_id)
        if not inv:
            raise ValueError(f"Investigation {inv_id} not found.")
        inv["status"]      = "APPROVED"
        inv["approved_at"] = _now()
        inv["approved_by"] = approved_by
        inv["human_notes"] = notes
        self._save(inv)
        print(f"  ✓ Investigation {inv_id} approved. Run: python3 integrations/investigator.py apply {inv_id}")
        return inv

    def reject(self, inv_id: str, notes: str = "") -> dict:
        """Human rejection — marks investigation as rejected."""
        inv = self._load(inv_id)
        if not inv:
            raise ValueError(f"Investigation {inv_id} not found.")
        inv["status"]      = "REJECTED"
        inv["human_notes"] = notes
        self._save(inv)
        print(f"  ✗ Investigation {inv_id} rejected: {notes}")
        return inv

    def apply_fixes(self, inv_id: str, push_to_git: bool = True) -> dict:
        """
        Apply all approved fixes:
        - Execute SQL fix_code statements
        - Apply dbt schema.yml updates
        - Commit + push to git if push_to_git=True
        """
        inv = self._load(inv_id)
        if not inv:
            raise ValueError(f"Investigation {inv_id} not found.")
        if inv["status"] != "APPROVED":
            raise ValueError(f"Investigation {inv_id} is not approved (status: {inv['status']}). Approve first.")

        applied = []
        fix_log = []

        for fix in inv.get("fixes", []):
            fix_type   = fix.get("fix_type")
            fix_code   = fix.get("fix_code")
            fix_action = fix.get("fix_action")

            print(f"  Applying fix: {fix_type} — {fix.get('description','')}")

            if fix_code and fix_code.strip().upper().startswith(("ALTER","CREATE","INSERT","UPDATE","MERGE")):
                # SQL fix
                conn = self._get_conn()
                if conn:
                    try:
                        cur = conn.cursor()
                        for stmt in fix_code.split(";"):
                            if stmt.strip():
                                cur.execute(stmt.strip())
                        applied.append({"fix_type": fix_type, "status": "applied", "code": fix_code})
                        fix_log.append(f"SQL applied: {fix_type}")
                    except Exception as e:
                        applied.append({"fix_type": fix_type, "status": "failed", "error": str(e)})
                        fix_log.append(f"SQL FAILED: {fix_type} — {e}")
                        print(f"    ✗ SQL fix failed: {e}")

            elif fix_code and fix_type == "dbt_schema_yml":
                # Write dbt schema updates
                schema_file = ROOT / "dbt" / "models" / "schema_updates.yml"
                schema_file.write_text(fix_code)
                applied.append({"fix_type": fix_type, "status": "written", "file": str(schema_file)})
                fix_log.append(f"dbt schema.yml updated: {schema_file}")

            else:
                # Manual fix — log it
                applied.append({"fix_type": fix_type, "status": "manual_required", "action": fix_action})
                fix_log.append(f"Manual fix required: {fix_type} — {fix_action}")
                print(f"    ℹ Manual fix required: {fix_action}")

        inv["status"]       = "APPLIED"
        inv["applied_at"]   = _now()
        inv["applied_fixes"] = applied
        inv["fix_log"]       = fix_log
        self._save(inv)

        # Write fix report
        fix_report_path = FIXES_DIR / f"{inv_id}_fix_report.md"
        fix_report_path.write_text(self._build_fix_report(inv, applied))

        # Git push
        if push_to_git:
            commit_msg = f"fix: investigation {inv_id} — {inv['pipeline']} — approved by {inv.get('approved_by','human')}"
            self._git_commit_and_push([str(fix_report_path)], commit_msg)
            inv["git_commit"] = commit_msg
            self._save(inv)

        print(f"\n  ✓ Fixes applied for {inv_id}. Report: {fix_report_path}")
        return inv

    # ── Report builders ────────────────────────────────────────────────────

    def _build_summary(self, findings: list, fixes: list) -> str:
        if not findings:
            return "No issues found. All checks passed."
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        high     = [f for f in findings if f["severity"] == "HIGH"]
        medium   = [f for f in findings if f["severity"] == "MEDIUM"]
        lines = [f"Found {len(findings)} issue(s):"]
        if critical: lines.append(f"  🔴 CRITICAL ({len(critical)}): " + "; ".join(f["finding"][:80] for f in critical))
        if high:     lines.append(f"  🟠 HIGH     ({len(high)}): " + "; ".join(f["finding"][:80] for f in high))
        if medium:   lines.append(f"  🟡 MEDIUM   ({len(medium)}): " + "; ".join(f["finding"][:80] for f in medium))
        if fixes:    lines.append(f"  {len(fixes)} fix(es) proposed.")
        return "\n".join(lines)

    def _print_report(self, inv: dict) -> None:
        print(f"\n  Investigation Report: {inv['id']}")
        print(f"  Pipeline: {inv['pipeline']}  |  Overall: {inv['overall']}")
        print(f"  Findings: {len(inv['findings'])}")
        for f in inv["findings"]:
            sev = {"CRITICAL":"🔴","HIGH":"🟠","MEDIUM":"🟡","LOW":"🔵"}.get(f["severity"],"⚪")
            print(f"    {sev} [{f['check']:20s}] {f['finding'][:80]}")
        if inv["fixes"]:
            print(f"\n  Proposed fixes ({len(inv['fixes'])}):")
            for fix in inv["fixes"]:
                print(f"    · {fix.get('fix_type'):25s} {fix.get('description','')}")
        print(f"\n  Status: {inv['status']}")
        print(f"  To approve: python3 integrations/investigator.py approve {inv['id']}")

    def _build_fix_report(self, inv: dict, applied: list) -> str:
        lines = [
            f"# Fix Report — {inv['id']}",
            f"",
            f"**Pipeline:** {inv['pipeline']}",
            f"**Investigated:** {inv['investigated_at'][:19]}",
            f"**Approved by:** {inv.get('approved_by','—')} at {inv.get('approved_at','—')[:19] if inv.get('approved_at') else '—'}",
            f"**Applied:** {inv.get('applied_at','—')[:19] if inv.get('applied_at') else '—'}",
            f"",
            f"## Findings Summary",
            f"",
            inv["summary"],
            f"",
            f"## Applied Fixes",
            f"",
        ]
        for a in applied:
            status_icon = "✅" if a["status"] == "applied" else ("⚠️" if a["status"] == "manual_required" else "❌")
            lines.append(f"- {status_icon} **{a['fix_type']}** — {a['status']}")
            if a.get("code"):
                lines.append(f"  ```sql\n  {a['code'][:300]}\n  ```")
            if a.get("action"):
                lines.append(f"  Action required: {a['action']}")
        lines += [f"", f"## Human Notes", f"", inv.get("human_notes","—")]
        return "\n".join(lines)

    # ── Fix generators ─────────────────────────────────────────────────────

    def _propose_fixes(self, findings: list) -> list[dict]:
        fixes = []
        for f in findings:
            if not f.get("fix_type"):
                continue
            fix = {
                "fix_type":    f["fix_type"],
                "description": f["finding"][:100],
                "table":       f.get("table"),
                "fix_action":  f.get("fix_action"),
                "fix_code":    f.get("fix_code"),
            }
            fixes.append(fix)
        return fixes

    def _gen_add_columns_sql(self, schema: str, table: str, cols: list, previous: dict) -> str:
        stmts = []
        for col in cols:
            dtype = previous.get(col, {}).get("type", "VARCHAR(256)")
            stmts.append(f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS {col} {dtype};")
        return "\n".join(stmts)

    def _gen_null_fix_sql(self, schema: str, table: str, col: str) -> str:
        return (
            f"-- Investigate null {col} values\n"
            f"SELECT COUNT(*), '{col}' AS col FROM {schema}.{table} WHERE {col} IS NULL;\n\n"
            f"-- Option: fill with default (adjust as needed)\n"
            f"-- UPDATE {schema}.{table} SET {col} = 'UNKNOWN' WHERE {col} IS NULL;"
        )

    def _gen_schema_yml_columns(self, added: list, current: dict) -> str:
        lines = ["      # New columns — add to schema.yml:"]
        for col in added:
            dtype = current.get(col, {}).get("type", "string")
            lines.append(f"      - name: {col.lower()}")
            lines.append(f"        description: ''  # TODO: document this column")
            lines.append(f"        # data_type: {dtype.lower()}")
        return "\n".join(lines)

    def _git_commit_and_push(self, files: list[str], message: str) -> None:
        try:
            for f in files:
                subprocess.run(["git", "add", f], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(ROOT), check=True, capture_output=True,
            )
            subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True, capture_output=True)
            print(f"  ✓ Git commit + push: {message[:60]}")
        except subprocess.CalledProcessError as e:
            print(f"  [git] Push failed: {e.stderr.decode() if e.stderr else e}")

    def _send_alert(self, inv: dict) -> None:
        try:
            from integrations.alerts import Alert, Severity
            sev = Severity.CRITICAL if inv["overall"] == "CRITICAL" else Severity.HIGH
            self._get_alerts().send(Alert(
                title    = f"Investigation {inv['id']}: {inv['pipeline']} — {inv['overall']}",
                body     = inv["summary"],
                severity = sev,
                source   = "investigator_agent",
                pipeline = inv["pipeline"],
                ticket   = inv["id"],
                metrics  = {
                    "critical": len([f for f in inv["findings"] if f["severity"]=="CRITICAL"]),
                    "high":     len([f for f in inv["findings"] if f["severity"]=="HIGH"]),
                    "total":    len(inv["findings"]),
                },
            ))
        except Exception as e:
            print(f"  [Alert] Failed: {e}")

    # ── State helpers ──────────────────────────────────────────────────────

    def _save(self, inv: dict) -> None:
        (INVESTIGATIONS_DIR / f"{inv['id']}.json").write_text(json.dumps(inv, indent=2, default=str))

    def _load(self, inv_id: str) -> Optional[dict]:
        p = INVESTIGATIONS_DIR / f"{inv_id}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def list_all(self, status: str = None) -> list[dict]:
        items = []
        for f in sorted(INVESTIGATIONS_DIR.glob("INV-*.json"), reverse=True):
            inv = json.loads(f.read_text())
            if status and inv.get("status") != status:
                continue
            items.append(inv)
        return items

    def print_list(self, status: str = None) -> None:
        items = self.list_all(status)
        if not items:
            print("  No investigations found.")
            return
        print(f"\n  {'ID':12s} {'PIPELINE':25s} {'OVERALL':10s} {'STATUS':18s} {'DATE'}")
        print("  " + "-" * 80)
        for i in items:
            print(
                f"  {i['id']:12s} {i['pipeline']:25s} {i['overall']:10s} "
                f"{i['status']:18s} {i['investigated_at'][:10]}"
            )


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    # Default pipeline tables mapping
    PIPELINE_TABLES = {
        "nwt_batch_load":  ["NWT_ORDER_FILE", "NWT_ORDER_PRODUCT_FILE", "NWT_STORE_FILE"],
        "dbt_star_schema": ["FACT_ORDER", "DIM_STORE", "DIM_DATE", "DIM_DAYPART"],
        "all":             ["NWT_ORDER_FILE", "FACT_ORDER", "DIM_STORE", "DIM_DATE"],
    }

    p = argparse.ArgumentParser(description="NGR Pipeline Investigator")
    sub = p.add_subparsers(dest="cmd")

    inv_p = sub.add_parser("investigate")
    inv_p.add_argument("--pipeline", required=True)
    inv_p.add_argument("--database", default="NISHANT_DS_DB")
    inv_p.add_argument("--schema",   default="NISHANT_WORKFLOW_TEST")
    inv_p.add_argument("--no-alert", action="store_true")

    sub.add_parser("list").add_argument("--status", nargs="?")
    sub.add_parser("show").add_argument("id")

    ap = sub.add_parser("approve")
    ap.add_argument("id")
    ap.add_argument("--notes", default="Approved")
    ap.add_argument("--by",    default="human")

    rp = sub.add_parser("reject")
    rp.add_argument("id")
    rp.add_argument("--notes", required=True)

    fx = sub.add_parser("apply")
    fx.add_argument("id")
    fx.add_argument("--no-push", action="store_true")

    args = p.parse_args()
    engine = InvestigationEngine()

    if args.cmd == "investigate":
        tables = PIPELINE_TABLES.get(args.pipeline, [])
        engine.run_investigation(
            pipeline   = args.pipeline,
            tables     = tables,
            database   = args.database,
            schema     = args.schema,
            auto_alert = not args.no_alert,
        )
    elif args.cmd == "list":
        engine.print_list(getattr(args, "status", None))
    elif args.cmd == "show":
        inv = engine._load(args.id)
        if inv:
            print(json.dumps(inv, indent=2, default=str))
        else:
            print(f"Not found: {args.id}")
    elif args.cmd == "approve":
        engine.approve(args.id, notes=args.notes, approved_by=args.by)
    elif args.cmd == "reject":
        engine.reject(args.id, notes=args.notes)
    elif args.cmd == "apply":
        engine.apply_fixes(args.id, push_to_git=not args.no_push)


if __name__ == "__main__":
    main()
