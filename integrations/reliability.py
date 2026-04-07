#!/usr/bin/env python3
"""
integrations/reliability.py — Data Reliability Engine

Implements Data Reliability Engineering (DRE) principles:
  - SLO/SLA tracking per pipeline
  - Incident lifecycle management (open → investigating → resolved)
  - Root cause analysis framework
  - Pipeline health scoring
  - Automated JIRA incident tickets
  - Multi-channel alerting on threshold breach

Usage:
  python3 integrations/reliability.py monitor          # full pipeline health check
  python3 integrations/reliability.py incident open    # open a new incident
  python3 integrations/reliability.py incident list    # list active incidents
  python3 integrations/reliability.py slo status       # SLO compliance summary
  python3 integrations/reliability.py runbook <name>   # print runbook for pipeline
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

INCIDENTS_DIR  = ROOT / "tasks" / "incidents"
INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)

SLO_BASELINE   = ROOT / "observability" / "snapshots" / "slo_baseline.json"


# ── Reliability Principles ─────────────────────────────────────────────────
#
# Applied to every pipeline:
#   1. Freshness SLO     — data arrives within the agreed window
#   2. Volume SLO        — row count within ±N% of rolling baseline
#   3. Schema SLO        — zero unexpected column removals
#   4. Completeness SLO  — null rate on critical columns < threshold
#   5. Uniqueness SLO    — duplicate keys = 0
#   6. Accuracy SLO      — cross-layer discrepancy < 1%
#   7. Availability SLO  — pipeline runs N% of expected runs (99.5% default)

PIPELINE_SLOS = {
    "nwt_batch_load": {
        "description":      "NWT orders batch load (Glue → Snowflake)",
        "schedule":         "daily",
        "expected_run_hours": [6],
        "freshness_slo_hours": 2,
        "volume_warn_pct":     5,
        "volume_fail_pct":    20,
        "null_columns":        ["order_id", "store_id", "business_date", "net_sales"],
        "pk_columns":          ["order_id"],
        "cross_layer_check":   "orders_curated_vs_dbt",
        "owner":               "data_engineer",
        "runbook":             "runbooks/nwt_batch_load.md",
        "availability_slo":    0.995,
    },
    "dbt_star_schema": {
        "description":      "dbt star schema run (FACT_ORDER + DIM_*)",
        "schedule":         "daily",
        "expected_run_hours": [7],
        "freshness_slo_hours": 3,
        "volume_warn_pct":     2,
        "volume_fail_pct":    10,
        "null_columns":        ["order_id", "store_sk", "date_sk", "net_sales"],
        "pk_columns":          ["order_id"],
        "cross_layer_check":   "orders_dbt_vs_report",
        "owner":               "analytics_engineer",
        "runbook":             "runbooks/dbt_star_schema.md",
        "availability_slo":    0.995,
    },
    "nwt_streaming": {
        "description":      "NWT Kafka streaming → Snowflake",
        "schedule":         "continuous",
        "freshness_slo_hours": 0.5,
        "lag_warn_msgs":     10_000,
        "lag_fail_msgs":    100_000,
        "owner":               "streaming_engineer",
        "runbook":             "runbooks/nwt_streaming.md",
        "availability_slo":    0.999,
    },
}


# ── Incident severity and status ───────────────────────────────────────────

class IncidentSeverity:
    P1 = "P1-CRITICAL"   # total data loss / outage — wake someone up
    P2 = "P2-HIGH"       # pipeline failed, SLA breached
    P3 = "P3-MEDIUM"     # degraded, warn threshold crossed
    P4 = "P4-LOW"        # advisory, no immediate action needed

class IncidentStatus:
    OPEN          = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    IDENTIFIED    = "IDENTIFIED"       # root cause known
    MITIGATING    = "MITIGATING"
    RESOLVED      = "RESOLVED"
    CLOSED        = "CLOSED"

SEVERITY_TO_ALERT = {
    IncidentSeverity.P1: "CRITICAL",
    IncidentSeverity.P2: "HIGH",
    IncidentSeverity.P3: "MEDIUM",
    IncidentSeverity.P4: "LOW",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:6].upper()


# ── Incident Manager ───────────────────────────────────────────────────────

class IncidentManager:
    """
    Full incident lifecycle: open → investigate → identify → mitigate → resolve.
    Automatically creates JIRA tickets and sends multi-channel alerts.
    """

    def __init__(self, alert_engine=None, jira_client=None, jira_project: str = None):
        self._alert  = alert_engine
        self._jira   = jira_client
        self._jira_project = jira_project or os.environ.get("NGR_JIRA_INCIDENT_PROJECT", "")

    def _get_alert(self):
        if self._alert is None:
            from integrations.alerts import AlertEngine
            self._alert = AlertEngine()
        return self._alert

    def _get_jira(self):
        if self._jira is None:
            try:
                from integrations.jira import JiraClient
                self._jira = JiraClient()
            except Exception:
                pass
        return self._jira

    # ── Open ──────────────────────────────────────────────────────────────

    def open(
        self,
        title:       str,
        description: str,
        severity:    str    = IncidentSeverity.P2,
        pipeline:    str    = "",
        source:      str    = "reliability_agent",
        metrics:     dict   = None,
        auto_jira:   bool   = True,
        auto_alert:  bool   = True,
    ) -> dict:
        """
        Open a new incident. Returns the incident dict.
        Automatically creates JIRA ticket + sends alerts if configured.
        """
        inc_id = f"INC-{_short_id()}"

        incident = {
            "id":           inc_id,
            "title":        title,
            "description":  description,
            "severity":     severity,
            "status":       IncidentStatus.OPEN,
            "pipeline":     pipeline,
            "source":       source,
            "metrics":      metrics or {},
            "opened_at":    _now(),
            "updated_at":   _now(),
            "events":       [],
            "rca":          {},     # root cause analysis
            "jira_key":     "",
            "resolution":   "",
        }

        # Save incident
        self._save(incident)

        # Create JIRA ticket
        if auto_jira and self._jira_project:
            jira_key = self._create_jira_incident(incident)
            incident["jira_key"] = jira_key
            self._save(incident)

        # Send alerts
        if auto_alert:
            self._alert_incident(incident)

        print(f"  🚨 Incident opened: {inc_id} [{severity}] {title}")
        return incident

    def update(
        self,
        inc_id:     str,
        status:     str,
        notes:      str = "",
        rca_update: dict = None,
        resolver:   str  = "",
    ) -> dict:
        """Update incident status with timeline event."""
        incident = self._load(inc_id)
        if not incident:
            raise ValueError(f"Incident {inc_id} not found.")

        old_status = incident["status"]
        incident["status"]     = status
        incident["updated_at"] = _now()

        event = {
            "ts":     _now(),
            "from":   old_status,
            "to":     status,
            "notes":  notes,
            "by":     resolver or "reliability_agent",
        }
        incident["events"].append(event)

        if rca_update:
            incident["rca"].update(rca_update)

        if status == IncidentStatus.RESOLVED:
            incident["resolved_at"] = _now()
            incident["resolution"]  = notes
            self._calculate_duration(incident)

        self._save(incident)

        # Update JIRA ticket
        jira = self._get_jira()
        if jira and incident.get("jira_key"):
            try:
                jira.comment(incident["jira_key"], f"Status → {status}: {notes}")
                if status == IncidentStatus.RESOLVED:
                    jira.transition(incident["jira_key"], "Done")
            except Exception as e:
                print(f"  [JIRA] Update failed: {e}")

        # Send resolved alert
        if status == IncidentStatus.RESOLVED:
            from integrations.alerts import Alert, Severity
            self._get_alert().send(Alert(
                title    = f"RESOLVED: {incident['title']}",
                body     = f"Incident {inc_id} resolved.\n\n{notes}",
                severity = Severity.RESOLVED,
                source   = "reliability_agent",
                pipeline = incident.get("pipeline", ""),
                ticket   = incident.get("jira_key", inc_id),
                metrics  = {"duration": incident.get("duration_minutes", "?")},
            ))

        print(f"  ✓ Incident {inc_id}: {old_status} → {status}")
        return incident

    def add_rca(
        self,
        inc_id:        str,
        root_cause:    str,
        contributing:  list = None,
        category:      str  = "",  # schema_change, infra_failure, bad_data, etc.
        action_items:  list = None,
    ) -> dict:
        """
        Record Root Cause Analysis.
        Categories: schema_change | infra_failure | bad_data | code_bug |
                    capacity | dependency_failure | config_change | unknown
        """
        rca = {
            "root_cause":        root_cause,
            "contributing_factors": contributing or [],
            "category":          category,
            "action_items":      action_items or [],
            "recorded_at":       _now(),
        }
        return self.update(inc_id, IncidentStatus.IDENTIFIED, notes=root_cause, rca_update=rca)

    def list_active(self) -> list[dict]:
        incidents = []
        for f in sorted(INCIDENTS_DIR.glob("*.json"), reverse=True):
            inc = json.loads(f.read_text())
            if inc["status"] not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                incidents.append(inc)
        return incidents

    def list_all(self, limit: int = 50) -> list[dict]:
        incidents = []
        for f in sorted(INCIDENTS_DIR.glob("*.json"), reverse=True)[:limit]:
            incidents.append(json.loads(f.read_text()))
        return incidents

    def print_summary(self) -> None:
        incidents = self.list_active()
        if not incidents:
            print("  No active incidents.")
            return
        print(f"\n  {'ID':12s} {'SEV':14s} {'STATUS':15s} {'PIPELINE':20s} {'TITLE'}")
        print("  " + "-" * 80)
        for i in incidents:
            print(
                f"  {i['id']:12s} {i['severity']:14s} {i['status']:15s} "
                f"{i.get('pipeline',''):20s} {i['title'][:40]}"
            )

    # ── Internal ───────────────────────────────────────────────────────────

    def _save(self, incident: dict) -> None:
        path = INCIDENTS_DIR / f"{incident['id']}.json"
        path.write_text(json.dumps(incident, indent=2, default=str))

    def _load(self, inc_id: str) -> Optional[dict]:
        path = INCIDENTS_DIR / f"{inc_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def _alert_incident(self, incident: dict) -> None:
        from integrations.alerts import Alert, Severity
        sev_str   = SEVERITY_TO_ALERT.get(incident["severity"], "HIGH")
        sev       = Severity[sev_str]
        slo_info  = PIPELINE_SLOS.get(incident.get("pipeline",""), {})
        runbook   = slo_info.get("runbook", "")

        links = {}
        if incident.get("jira_key"):
            links["JIRA Incident"] = f"{os.environ.get('NGR_JIRA_BASE_URL','')}/browse/{incident['jira_key']}"

        self._get_alert().send(Alert(
            title    = incident["title"],
            body     = incident["description"],
            severity = sev,
            source   = incident["source"],
            pipeline = incident.get("pipeline", ""),
            ticket   = incident.get("jira_key", incident["id"]),
            metrics  = incident.get("metrics", {}),
            links    = links,
            runbook  = runbook,
        ))

    def _create_jira_incident(self, incident: dict) -> str:
        jira = self._get_jira()
        if not jira:
            return ""
        try:
            priority_map = {
                IncidentSeverity.P1: "Critical",
                IncidentSeverity.P2: "High",
                IncidentSeverity.P3: "Medium",
                IncidentSeverity.P4: "Low",
            }
            body = (
                f"*Incident ID:* {incident['id']}\n"
                f"*Pipeline:* {incident.get('pipeline','unknown')}\n"
                f"*Detected by:* {incident['source']}\n"
                f"*Time:* {incident['opened_at']}\n\n"
                f"{incident['description']}\n\n"
                f"*Metrics:*\n" + "\n".join(f"- {k}: {v}" for k, v in incident.get("metrics",{}).items())
            )
            result = jira.create_ticket(
                project_key = self._jira_project,
                summary     = f"[{incident['severity']}] {incident['title']}",
                description = body,
                issue_type  = "Incident",
                priority    = priority_map.get(incident["severity"], "High"),
                labels      = ["data-incident", "ngr-auto"],
            )
            return result.get("key", "")
        except Exception as e:
            print(f"  [JIRA] Failed to create incident ticket: {e}")
            return ""

    def _calculate_duration(self, incident: dict) -> None:
        try:
            opened   = datetime.fromisoformat(incident["opened_at"])
            resolved = datetime.fromisoformat(incident["resolved_at"])
            mins     = int((resolved - opened).total_seconds() / 60)
            incident["duration_minutes"] = mins
        except Exception:
            pass


# ── Pipeline Monitor ───────────────────────────────────────────────────────

class PipelineMonitor:
    """
    Runs reliability checks on all configured pipelines.
    Opens incidents automatically when thresholds are breached.
    """

    def __init__(self, incident_manager: IncidentManager = None):
        self._inc = incident_manager or IncidentManager()

    def run_all(self, auto_incident: bool = True) -> dict:
        """
        Run full reliability checks for all configured pipelines.
        Returns dict of {pipeline: health_score (0-100)}.
        """
        scores = {}
        for pipeline, slo in PIPELINE_SLOS.items():
            score = self._check_pipeline(pipeline, slo, auto_incident)
            scores[pipeline] = score

        # Print summary
        print(f"\n  {'Pipeline':<30} {'Score':>6}  {'Status'}")
        print("  " + "-" * 55)
        for pipeline, score in scores.items():
            status = "✅ HEALTHY" if score >= 90 else "⚠ DEGRADED" if score >= 70 else "🔴 CRITICAL"
            print(f"  {pipeline:<30} {score:>5}%  {status}")

        return scores

    def _check_pipeline(self, pipeline: str, slo: dict, auto_incident: bool) -> int:
        """Run all checks for a pipeline. Returns health score 0-100."""
        issues  = []
        score   = 100

        try:
            results = self._run_observability(pipeline, slo)
        except Exception as e:
            issues.append(f"Observability check error: {e}")
            return 0

        # Freshness check
        freshness = results.get("freshness", {})
        if freshness.get("status") == "fail":
            hours = freshness.get("hours_stale", "?")
            issues.append(f"Freshness FAIL: {hours}h stale (SLO: {slo.get('freshness_slo_hours',2)}h)")
            score -= 30
        elif freshness.get("status") == "warn":
            issues.append(f"Freshness WARN: {freshness.get('hours_stale','?')}h stale")
            score -= 10

        # Volume check
        volume = results.get("row_count", {})
        if volume.get("status") == "fail":
            drop = volume.get("drop_pct", "?")
            issues.append(f"Volume FAIL: {drop}% drop")
            score -= 25
        elif volume.get("status") == "warn":
            issues.append(f"Volume WARN: {volume.get('drop_pct','?')}% drop")
            score -= 8

        # Null check
        nulls = results.get("nulls", {})
        if nulls.get("status") == "fail":
            issues.append(f"Nulls FAIL: {nulls.get('details','')}")
            score -= 20
        elif nulls.get("status") == "warn":
            score -= 5

        # Duplicates
        dups = results.get("duplicates", {})
        if dups.get("status") == "fail":
            issues.append(f"Duplicates FAIL: {dups.get('count','?')} duplicate PKs")
            score -= 25

        # Schema drift
        schema = results.get("schema_drift", {})
        if schema.get("status") == "fail":
            issues.append(f"Schema drift FAIL: {schema.get('details','')}")
            score -= 20
        elif schema.get("status") == "warn":
            score -= 5

        score = max(0, score)

        # Auto-open incident
        if auto_incident and issues:
            severity = IncidentSeverity.P1 if score < 40 else (
                       IncidentSeverity.P2 if score < 70 else IncidentSeverity.P3)
            self._open_pipeline_incident(pipeline, slo, issues, results, severity, score)

        return score

    def _run_observability(self, pipeline: str, slo: dict) -> dict:
        """Call the observability observer and return check results."""
        try:
            import subprocess, json as _json
            result = subprocess.run(
                ["python3", "observability/observer.py", "run", "--json"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                return _json.loads(result.stdout)
        except Exception:
            pass
        # Fallback: return empty (observer not available)
        return {}

    def _open_pipeline_incident(
        self,
        pipeline:  str,
        slo:       dict,
        issues:    list,
        metrics:   dict,
        severity:  str,
        score:     int,
    ) -> None:
        # Check if there's already an open incident for this pipeline
        for inc in self._inc.list_active():
            if inc.get("pipeline") == pipeline:
                return  # already tracking

        self._inc.open(
            title       = f"Pipeline degraded: {pipeline}",
            description = (
                f"Reliability check failed for **{pipeline}**.\n\n"
                f"**Health Score:** {score}/100\n\n"
                f"**Issues detected:**\n" + "\n".join(f"- {i}" for i in issues) +
                f"\n\n**SLO Config:**\n"
                f"- Freshness SLO: {slo.get('freshness_slo_hours','?')}h\n"
                f"- Volume warn: {slo.get('volume_warn_pct','?')}%\n"
                f"- Owner: {slo.get('owner','?')}"
            ),
            severity    = severity,
            pipeline    = pipeline,
            metrics     = {
                "health_score":   score,
                "issues_count":   len(issues),
                **{k: v for k, v in metrics.items() if isinstance(v, (int, float, str))},
            },
        )


# ── SLO Tracker ───────────────────────────────────────────────────────────

class SLOTracker:
    """
    Track SLO compliance over a rolling window.
    Loads run history from observability/runs/*.json.
    """

    def __init__(self):
        self.runs_dir = ROOT / "observability" / "runs"

    def compliance(self, pipeline: str = None, days: int = 30) -> dict:
        """
        Calculate SLO compliance % per pipeline over last N days.
        Returns {pipeline: {"availability": 99.2, "freshness": 98.1, ...}}
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results = {}

        for pipeline_key, slo_cfg in PIPELINE_SLOS.items():
            if pipeline and pipeline_key != pipeline:
                continue
            runs = self._load_runs(pipeline_key, cutoff)
            if not runs:
                results[pipeline_key] = {"error": "no run data"}
                continue

            total   = len(runs)
            passes  = sum(1 for r in runs if r.get("status") == "pass")
            fresh   = sum(1 for r in runs if r.get("freshness", {}).get("status") != "fail")
            volume  = sum(1 for r in runs if r.get("row_count", {}).get("status") != "fail")
            schema  = sum(1 for r in runs if r.get("schema_drift", {}).get("status") != "fail")

            results[pipeline_key] = {
                "availability_pct": round(passes   / total * 100, 2),
                "freshness_pct":    round(fresh     / total * 100, 2),
                "volume_pct":       round(volume    / total * 100, 2),
                "schema_pct":       round(schema    / total * 100, 2),
                "total_runs":       total,
                "target_availability": slo_cfg.get("availability_slo", 0.995) * 100,
            }

        return results

    def print_slo_report(self, days: int = 30) -> None:
        results = self.compliance(days=days)
        print(f"\n  SLO Compliance Report (last {days} days)")
        print("  " + "=" * 75)
        print(f"  {'Pipeline':<30} {'Avail%':>7} {'Target%':>8} {'Fresh%':>7} {'Vol%':>7} {'Schema%':>8}")
        print("  " + "-" * 75)
        for pipeline, r in results.items():
            if "error" in r:
                print(f"  {pipeline:<30}  {'(no data)':>35}")
                continue
            avail_ok = "✅" if r["availability_pct"] >= r["target_availability"] else "🔴"
            print(
                f"  {pipeline:<30} "
                f"{r['availability_pct']:>6.1f}% "
                f"{r['target_availability']:>7.1f}% {avail_ok} "
                f"{r['freshness_pct']:>6.1f}% "
                f"{r['volume_pct']:>6.1f}% "
                f"{r['schema_pct']:>7.1f}%"
            )

    def _load_runs(self, pipeline: str, cutoff: datetime) -> list:
        runs = []
        if not self.runs_dir.exists():
            return runs
        for f in sorted(self.runs_dir.glob("run_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                ts   = datetime.fromisoformat(data.get("timestamp", "").replace("Z", "+00:00"))
                if ts < cutoff:
                    break
                # Filter to this pipeline's checks if tagged
                if data.get("pipeline") == pipeline or not data.get("pipeline"):
                    runs.append(data)
            except Exception:
                continue
        return runs


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    p = argparse.ArgumentParser(description="NGR Data Reliability Engine")
    sub = p.add_subparsers(dest="cmd")

    # monitor
    mon = sub.add_parser("monitor", help="Run full pipeline reliability check")
    mon.add_argument("--no-incident", action="store_true")

    # incident
    inc = sub.add_parser("incident", help="Incident management")
    isub = inc.add_subparsers(dest="inc_cmd")

    io = isub.add_parser("open")
    io.add_argument("--title", required=True)
    io.add_argument("--desc",  default="")
    io.add_argument("--severity", default="P2-HIGH",
                    choices=["P1-CRITICAL","P2-HIGH","P3-MEDIUM","P4-LOW"])
    io.add_argument("--pipeline", default="")

    iu = isub.add_parser("update")
    iu.add_argument("id")
    iu.add_argument("--status", required=True,
                    choices=["INVESTIGATING","IDENTIFIED","MITIGATING","RESOLVED","CLOSED"])
    iu.add_argument("--notes", default="")

    ir = isub.add_parser("rca")
    ir.add_argument("id")
    ir.add_argument("--cause",    required=True)
    ir.add_argument("--category", default="unknown")
    ir.add_argument("--actions",  nargs="+", default=[])

    isub.add_parser("list")

    # slo
    sl = sub.add_parser("slo", help="SLO compliance report")
    sl.add_argument("--days", type=int, default=30)

    # alert test
    at = sub.add_parser("test-alert", help="Send a test alert to all channels")
    at.add_argument("--severity", default="MEDIUM")

    args = p.parse_args()

    if args.cmd == "monitor":
        monitor = PipelineMonitor()
        monitor.run_all(auto_incident=not args.no_incident)

    elif args.cmd == "incident":
        mgr = IncidentManager()
        if args.inc_cmd == "open":
            mgr.open(
                title       = args.title,
                description = args.desc,
                severity    = args.severity,
                pipeline    = args.pipeline,
            )
        elif args.inc_cmd == "update":
            mgr.update(args.id, status=args.status, notes=args.notes)
        elif args.inc_cmd == "rca":
            mgr.add_rca(args.id, root_cause=args.cause,
                        category=args.category, action_items=args.actions)
        elif args.inc_cmd == "list":
            mgr.print_summary()

    elif args.cmd == "slo":
        SLOTracker().print_slo_report(days=args.days)

    elif args.cmd == "test-alert":
        from integrations.alerts import Alert, Severity, AlertEngine
        engine = AlertEngine()
        print(f"Channels: {engine.configured_channels}")
        engine.send(Alert(
            title    = "Test Alert — MDW Reliability Agent",
            body     = "This is a test alert from the MDW Data Reliability Agent.",
            severity = Severity[args.severity],
            source   = "reliability_agent",
            pipeline = "nwt_batch_load",
            ticket   = "TEST-001",
            metrics  = {"health_score": 72, "rows_today": 32000, "rows_expected": 50000},
            links    = {"NGR Repo": "https://github.com/Nishant-Karri/Multi_Digital_Workers"},
        ))


if __name__ == "__main__":
    main()
