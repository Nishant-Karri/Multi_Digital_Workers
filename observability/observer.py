#!/usr/bin/env python3
"""
observer.py — Data Observability Engine

Runs quality checks and cross-layer comparisons across:
  Landing (S3/Glue) → Curated (Iceberg) → dbt (star schema) → Report layer

Usage:
  python3 observability/observer.py run              # Full suite
  python3 observability/observer.py run --layer dbt  # Single layer
  python3 observability/observer.py compare          # All layer comparisons
  python3 observability/observer.py compare --id orders_curated_vs_dbt
  python3 observability/observer.py freshness        # Freshness only
  python3 observability/observer.py schema           # Schema drift only
  python3 observability/observer.py report           # Last run report
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT     = Path(__file__).parent.parent
OBS_DIR  = ROOT / "observability"
SNAP_DIR = OBS_DIR / "snapshots"
RUNS_DIR = OBS_DIR / "runs"
CFG_FILE = OBS_DIR / "config.json"

SNAP_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))


def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_cfg():
    return json.loads(CFG_FILE.read_text())

def get_conn():
    from vault.vault import Connectors
    return Connectors().snowflake()

def run_query(conn, sql: str) -> list:
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0].lower() for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def scalar(conn, sql: str):
    rows = run_query(conn, sql)
    if rows:
        return list(rows[0].values())[0]
    return None

def fqn(cfg_layer: dict, table: str) -> str:
    return f"{cfg_layer['database']}.{cfg_layer['schema']}.{table}"


# ── Individual Checks ─────────────────────────────────────────────────────────

def check_freshness(conn, layer_name: str, layer_cfg: dict, check_cfg: dict) -> list:
    results = []
    ts_col  = check_cfg.get("timestamp_col", "insert_timestamp")
    warn_h  = check_cfg.get("warn_hours", 2)
    fail_h  = check_cfg.get("fail_hours", 24)

    for alias, table in layer_cfg["tables"].items():
        tbl = fqn(layer_cfg, table)
        try:
            sql = f"""
                SELECT DATEDIFF('hour', MAX({ts_col}), CURRENT_TIMESTAMP()) AS hours_ago
                FROM {tbl}
            """
            hours_ago = scalar(conn, sql)
            if hours_ago is None:
                status = "error"
            elif hours_ago >= fail_h:
                status = "fail"
            elif hours_ago >= warn_h:
                status = "warn"
            else:
                status = "pass"

            results.append({
                "check":     "freshness",
                "layer":     layer_name,
                "table":     table,
                "hours_ago": hours_ago,
                "status":    status,
            })
        except Exception as e:
            results.append({"check": "freshness", "layer": layer_name, "table": table,
                            "status": "error", "error": str(e)})
    return results


def check_row_counts(conn, layer_name: str, layer_cfg: dict, prev_snapshot: dict, warn_pct: float, fail_pct: float) -> list:
    results = []
    for alias, table in layer_cfg["tables"].items():
        tbl = fqn(layer_cfg, table)
        try:
            count = scalar(conn, f"SELECT COUNT(*) FROM {tbl}")
            prev  = prev_snapshot.get(f"{layer_name}.{table}", {}).get("row_count")

            if prev and prev > 0:
                drop_pct = max(0, (prev - count) / prev * 100)
                if drop_pct >= fail_pct:
                    status = "fail"
                elif drop_pct >= warn_pct:
                    status = "warn"
                else:
                    status = "pass"
            else:
                drop_pct = 0
                status   = "pass"

            results.append({
                "check":      "row_count",
                "layer":      layer_name,
                "table":      table,
                "count":      count,
                "prev_count": prev,
                "drop_pct":   round(drop_pct, 2),
                "status":     status,
            })
        except Exception as e:
            results.append({"check": "row_count", "layer": layer_name, "table": table,
                            "status": "error", "error": str(e)})
    return results


def check_nulls(conn, layer_name: str, layer_cfg: dict, null_cfg: dict) -> list:
    results = []
    fail_rate = null_cfg.get("fail_rate_pct", 5)
    col_map   = null_cfg.get("columns", {})

    for alias, table in layer_cfg["tables"].items():
        tbl  = fqn(layer_cfg, table)
        cols = col_map.get(table, [])
        if not cols:
            continue
        try:
            total = scalar(conn, f"SELECT COUNT(*) FROM {tbl}")
            if not total:
                continue
            for col in cols:
                null_count = scalar(conn, f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NULL")
                rate_pct   = round(null_count / total * 100, 2) if total else 0
                status     = "fail" if rate_pct >= fail_rate else ("warn" if rate_pct > 0 else "pass")
                results.append({
                    "check":      "nulls",
                    "layer":      layer_name,
                    "table":      table,
                    "column":     col,
                    "null_count": null_count,
                    "total":      total,
                    "rate_pct":   rate_pct,
                    "status":     status,
                })
        except Exception as e:
            results.append({"check": "nulls", "layer": layer_name, "table": table,
                            "status": "error", "error": str(e)})
    return results


def check_duplicates(conn, layer_name: str, layer_cfg: dict, dup_cfg: dict) -> list:
    results = []
    pk_map  = dup_cfg.get("primary_keys", {})

    for alias, table in layer_cfg["tables"].items():
        tbl = fqn(layer_cfg, table)
        pks = pk_map.get(table, [])
        if not pks:
            continue
        try:
            pk_list = ", ".join(pks)
            sql     = f"""
                SELECT COUNT(*) AS dup_count FROM (
                    SELECT {pk_list}, COUNT(*) AS n
                    FROM {tbl}
                    GROUP BY {pk_list}
                    HAVING COUNT(*) > 1
                )
            """
            dupes  = scalar(conn, sql)
            status = "fail" if dupes > 0 else "pass"
            results.append({
                "check":  "duplicates",
                "layer":  layer_name,
                "table":  table,
                "pks":    pks,
                "dupes":  dupes,
                "status": status,
            })
        except Exception as e:
            results.append({"check": "duplicates", "layer": layer_name, "table": table,
                            "status": "error", "error": str(e)})
    return results


def check_schema_drift(conn, layer_name: str, layer_cfg: dict) -> list:
    results = []
    for alias, table in layer_cfg["tables"].items():
        tbl       = fqn(layer_cfg, table)
        snap_file = SNAP_DIR / f"{layer_name}_{table}_schema.json"
        try:
            cols_now = run_query(conn, f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_catalog = '{layer_cfg["database"]}'
                  AND table_schema  = '{layer_cfg["schema"]}'
                  AND table_name    = '{table}'
                ORDER BY ordinal_position
            """)
            schema_now = {r["column_name"]: r["data_type"] for r in cols_now}

            if snap_file.exists():
                schema_prev = json.loads(snap_file.read_text())
                added   = [c for c in schema_now if c not in schema_prev]
                removed = [c for c in schema_prev if c not in schema_now]
                changed = [c for c in schema_now if c in schema_prev and schema_now[c] != schema_prev[c]]
                drifted = bool(added or removed or changed)
                status  = "fail" if (removed or changed) else ("warn" if added else "pass")
                results.append({
                    "check":   "schema_drift",
                    "layer":   layer_name,
                    "table":   table,
                    "drifted": drifted,
                    "added":   added,
                    "removed": removed,
                    "changed": changed,
                    "status":  status,
                })
            else:
                results.append({
                    "check":   "schema_drift",
                    "layer":   layer_name,
                    "table":   table,
                    "drifted": False,
                    "status":  "pass",
                    "note":    "First run — baseline snapshot saved",
                })
            # Save/update snapshot
            snap_file.write_text(json.dumps(schema_now, indent=2))
        except Exception as e:
            results.append({"check": "schema_drift", "layer": layer_name, "table": table,
                            "status": "error", "error": str(e)})
    return results


# ── Layer Comparisons ─────────────────────────────────────────────────────────

METRIC_QUERIES = {
    "row_count":          "SELECT COUNT(*) FROM {tbl}",
    "sum_net_sales":      "SELECT COALESCE(SUM(net_sales), 0) FROM {tbl}",
    "sum_gross_sales":    "SELECT COALESCE(SUM(gross_sales), 0) FROM {tbl}",
    "sum_discount_amount":"SELECT COALESCE(SUM(discount_amount), 0) FROM {tbl}",
    "distinct_store_ids": "SELECT COUNT(DISTINCT store_id) FROM {tbl}",
    "date_range":         "SELECT MIN(business_date) || ' to ' || MAX(business_date) FROM {tbl}",
}


def run_comparison(conn, comp: dict, cfg: dict) -> dict:
    src_layer = cfg["layers"][comp["source"]["layer"]]
    tgt_layer = cfg["layers"][comp["target"]["layer"]]
    src_tbl   = fqn(src_layer, comp["source"]["table"])
    tgt_tbl   = fqn(tgt_layer, comp["target"]["table"])
    metrics   = comp.get("metrics", ["row_count"])

    result = {
        "id":          comp["id"],
        "description": comp["description"],
        "source":      f"{comp['source']['layer']}.{comp['source']['table']}",
        "target":      f"{comp['target']['layer']}.{comp['target']['table']}",
        "metrics":     {},
        "status":      "pass",
        "discrepancies": [],
        "ts":          now_iso(),
    }

    for metric in metrics:
        sql_tmpl = METRIC_QUERIES.get(metric)
        if not sql_tmpl:
            continue
        try:
            src_val = scalar(conn, sql_tmpl.format(tbl=src_tbl))
            tgt_val = scalar(conn, sql_tmpl.format(tbl=tgt_tbl))

            match   = True
            pct_diff = 0.0
            if isinstance(src_val, (int, float)) and isinstance(tgt_val, (int, float)):
                if src_val > 0:
                    pct_diff = abs(src_val - tgt_val) / src_val * 100
                match    = pct_diff < 1.0  # < 1% tolerance
            else:
                match = str(src_val) == str(tgt_val)

            result["metrics"][metric] = {
                "source":   src_val,
                "target":   tgt_val,
                "pct_diff": round(pct_diff, 4),
                "match":    match,
            }

            if not match:
                result["discrepancies"].append({
                    "metric":   metric,
                    "source":   src_val,
                    "target":   tgt_val,
                    "pct_diff": round(pct_diff, 2),
                })
                result["status"] = "fail"

        except Exception as e:
            result["metrics"][metric] = {"error": str(e)}
            result["status"] = "error"

    return result


# ── Run Suite ─────────────────────────────────────────────────────────────────

def run_suite(layer_filter: str = None) -> dict:
    cfg  = load_cfg()
    conn = get_conn()

    # Load previous row-count snapshot
    prev_snap_file = SNAP_DIR / "row_counts.json"
    prev_snap      = json.loads(prev_snap_file.read_text()) if prev_snap_file.exists() else {}
    curr_snap      = {}

    all_results = []
    layers_to_run = (
        {layer_filter: cfg["layers"][layer_filter]} if layer_filter
        else cfg["layers"]
    )

    for layer_name, layer_cfg in layers_to_run.items():
        print(f"\n  Checking layer: {layer_name} ({layer_cfg['description']})")

        if cfg["checks"]["freshness"]["enabled"]:
            r = check_freshness(conn, layer_name, layer_cfg, cfg["checks"]["freshness"])
            all_results.extend(r)
            _print_results(r)

        rc_results = check_row_counts(
            conn, layer_name, layer_cfg, prev_snap,
            cfg["checks"]["row_count"]["warn_drop_pct"],
            cfg["checks"]["row_count"]["fail_drop_pct"],
        )
        all_results.extend(rc_results)
        _print_results(rc_results)
        for r in rc_results:
            curr_snap[f"{layer_name}.{r['table']}"] = {"row_count": r.get("count")}

        if cfg["checks"]["nulls"]["enabled"]:
            r = check_nulls(conn, layer_name, layer_cfg, cfg["checks"]["nulls"])
            all_results.extend(r)
            _print_results(r)

        if cfg["checks"]["duplicates"]["enabled"]:
            r = check_duplicates(conn, layer_name, layer_cfg, cfg["checks"]["duplicates"])
            all_results.extend(r)
            _print_results(r)

        if cfg["checks"]["schema_drift"]["enabled"]:
            r = check_schema_drift(conn, layer_name, layer_cfg)
            all_results.extend(r)
            _print_results(r)

    # Update row count snapshot
    merged_snap = {**prev_snap, **curr_snap}
    prev_snap_file.write_text(json.dumps(merged_snap, indent=2))

    conn.close()

    passed = sum(1 for r in all_results if r["status"] == "pass")
    warned = sum(1 for r in all_results if r["status"] == "warn")
    failed = sum(1 for r in all_results if r["status"] in ("fail","error"))
    total  = len(all_results)

    run = {
        "ts":      now_iso(),
        "total":   total,
        "passed":  passed,
        "warned":  warned,
        "failed":  failed,
        "results": all_results,
    }

    # Save run
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    layer = f"_{layer_filter}" if layer_filter else ""
    run_file = RUNS_DIR / f"run{layer}_{ts}.json"
    run_file.write_text(json.dumps(run, indent=2))

    print(f"\n{'='*55}")
    print(f"  Results: {passed}/{total} passed  |  {warned} warnings  |  {failed} failed")
    print(f"  Report saved: {run_file.name}")
    print(f"{'='*55}")

    return run


def run_comparisons(comp_id: str = None) -> list:
    cfg     = load_cfg()
    conn    = get_conn()
    comps   = cfg.get("comparisons", [])

    if comp_id:
        comps = [c for c in comps if c["id"] == comp_id]

    results = []
    print(f"\n  Running {len(comps)} comparison(s)...\n")

    for comp in comps:
        print(f"  [{comp['id']}] {comp['description']}")
        result = run_comparison(conn, comp, cfg)
        results.append(result)

        for metric, vals in result["metrics"].items():
            if "error" in vals:
                icon = "✗"
            elif vals.get("match"):
                icon = "✓"
            else:
                icon = "✗"
            src = vals.get("source","?")
            tgt = vals.get("target","?")
            pct = vals.get("pct_diff",0)
            print(f"    {icon} {metric:25s}  src={src}  tgt={tgt}  diff={pct:.2f}%")

        if result["discrepancies"]:
            print(f"\n    ⚠  DISCREPANCIES FOUND:")
            for d in result["discrepancies"]:
                print(f"       {d['metric']}: {d['source']} vs {d['target']} ({d['pct_diff']:.2f}% off)")
        print()

    conn.close()

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RUNS_DIR / f"comparisons_{ts}.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"  Comparison report saved: {out_file.name}")
    return results


def _print_results(results: list):
    icons = {"pass": "✓", "warn": "⚠", "fail": "✗", "error": "✗"}
    for r in results:
        icon  = icons.get(r["status"], "?")
        check = r.get("check","?")
        table = r.get("table","?")
        col   = f".{r['column']}" if r.get("column") else ""
        detail = ""
        if check == "freshness":
            detail = f"{r.get('hours_ago','?')}h ago"
        elif check == "row_count":
            detail = f"{r.get('count','?'):,} rows"
            if r.get("drop_pct"):
                detail += f" (↓{r['drop_pct']}%)"
        elif check == "nulls":
            detail = f"{r.get('null_count',0):,} nulls ({r.get('rate_pct',0)}%)"
        elif check == "duplicates":
            detail = f"{r.get('dupes',0):,} dupes"
        elif check == "schema_drift":
            if r.get("added"):
                detail += f"+{len(r['added'])} cols "
            if r.get("removed"):
                detail += f"-{len(r['removed'])} cols "
        print(f"    {icon} {check:15s} {table}{col:40s} {detail}")


def show_report(args=None):
    runs = sorted(RUNS_DIR.glob("run_*.json"), reverse=True)
    if not runs:
        print("No runs found. Run: python3 observability/observer.py run")
        return
    latest = json.loads(runs[0].read_text())
    print(f"\nLast run: {latest['ts']}")
    print(f"  {latest['passed']}/{latest['total']} passed  |  {latest['warned']} warnings  |  {latest['failed']} failed\n")

    fails = [r for r in latest["results"] if r["status"] in ("fail","error","warn")]
    if not fails:
        print("  ✓ All checks passed.")
        return
    print("  Issues:")
    for r in fails:
        icon = "✗" if r["status"] in ("fail","error") else "⚠"
        print(f"    {icon} [{r['layer']}] {r['table']} — {r['check']}: {r.get('error', r.get('detail',''))}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(prog="observer", description="Data Observability Engine")
    s = p.add_subparsers(dest="cmd")

    rp = s.add_parser("run", help="Run full check suite")
    rp.add_argument("--layer", help="Run only this layer (landing/curated/dbt/report)")

    cp = s.add_parser("compare", help="Run cross-layer comparisons")
    cp.add_argument("--id", help="Run only this comparison ID")

    s.add_parser("freshness", help="Freshness checks only")
    s.add_parser("schema",    help="Schema drift checks only")
    s.add_parser("report",    help="Show last run report")

    args = p.parse_args()

    if args.cmd == "run":
        run_suite(getattr(args,"layer",None))
    elif args.cmd == "compare":
        run_comparisons(getattr(args,"id",None))
    elif args.cmd == "freshness":
        run_suite.__doc__
        cfg  = load_cfg()
        conn = get_conn()
        all_r = []
        for name, lcfg in cfg["layers"].items():
            all_r.extend(check_freshness(conn, name, lcfg, cfg["checks"]["freshness"]))
        conn.close()
        _print_results(all_r)
    elif args.cmd == "schema":
        cfg  = load_cfg()
        conn = get_conn()
        all_r = []
        for name, lcfg in cfg["layers"].items():
            all_r.extend(check_schema_drift(conn, name, lcfg))
        conn.close()
        _print_results(all_r)
    elif args.cmd == "report":
        show_report()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
