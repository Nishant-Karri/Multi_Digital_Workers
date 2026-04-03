#!/usr/bin/env python3
"""
scheduler.py — Task Scheduler & Decomposer

Classifies tasks by size (small/medium/large/epic) and decomposes
large/epic tasks into parallelizable subtasks for multiple workers.

Usage:
  python3 scheduler.py classify <task_id>          # Auto-classify task size
  python3 scheduler.py decompose <task_id>         # Break large/epic into subtasks
  python3 scheduler.py dispatch                    # Dispatch all ready tasks to workers
  python3 scheduler.py pipeline create <name>      # Create a multi-stage pipeline
  python3 scheduler.py pipeline status <name>      # Pipeline progress
  python3 scheduler.py pipeline list               # All active pipelines
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT         = Path(__file__).parent
TASKS_INBOX  = ROOT / "tasks" / "inbox"
TASKS_ACTIVE = ROOT / "tasks" / "active"
TASKS_DONE   = ROOT / "tasks" / "completed"
PIPELINE_DIR = ROOT / "tasks" / "pipelines"
CONFIG_FILE  = ROOT / "config" / "scaling.json"

PIPELINE_DIR.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()

def short_id():
    return str(uuid.uuid4())[:8]

def load_config():
    return json.loads(CONFIG_FILE.read_text())

def load_task(task_id: str) -> dict:
    for d in [TASKS_INBOX, TASKS_ACTIVE]:
        f = d / f"{task_id}.json"
        if f.exists():
            return json.loads(f.read_text()), f
    return {}, None


# ── Classification ────────────────────────────────────────────────────────────

def classify_task(task: dict) -> str:
    """
    Auto-classify task size based on title, description, and tags.
    Returns: small | medium | large | epic
    """
    cfg        = load_config()
    text       = (task.get("title","") + " " + task.get("description","")).lower()
    size_hint  = task.get("size", "").lower()

    if size_hint in ("small","medium","large","epic"):
        return size_hint

    epic_kws  = cfg["auto_classify"]["keywords_epic"]
    large_kws = cfg["auto_classify"]["keywords_large"]

    if any(kw in text for kw in epic_kws):
        return "epic"
    if any(kw in text for kw in large_kws):
        return "large"

    # Heuristic: subtask count in description
    steps = text.count("\n-") + text.count("\n*") + text.count("\n1.")
    if steps >= 8:
        return "epic"
    if steps >= 3:
        return "large"
    if len(text) > 500:
        return "medium"
    return "small"


def cmd_classify(args):
    task, _ = load_task(args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        return
    size = classify_task(task)
    cfg  = load_config()["task_sizes"][size]
    print(f"Task {args.task_id}: {task.get('title','?')}")
    print(f"  Size:        {size}")
    print(f"  Max workers: {cfg['max_workers']}")
    print(f"  Timeout:     {cfg['timeout_minutes']} min")
    print(f"  Description: {cfg['description']}")

    if size in ("large","epic"):
        print(f"\n  → Run: python3 scheduler.py decompose {args.task_id}")


# ── Decomposition ─────────────────────────────────────────────────────────────

DECOMPOSITION_TEMPLATES = {
    "etl": [
        {"title": "Extract: read source data",          "role": "data",    "stage": 1},
        {"title": "Transform: clean and validate",      "role": "data",    "stage": 2},
        {"title": "Load: write to destination",         "role": "data",    "stage": 3},
        {"title": "Validate: row counts and checksums", "role": "review",  "stage": 4},
    ],
    "feature": [
        {"title": "Design: spec and approach",    "role": "general", "stage": 1},
        {"title": "Implement: write code",        "role": "code",    "stage": 2},
        {"title": "Test: unit and integration",   "role": "review",  "stage": 3},
        {"title": "Review: code quality gate",    "role": "review",  "stage": 4},
    ],
    "migration": [
        {"title": "Audit: inventory existing state",       "role": "data",  "stage": 1},
        {"title": "Plan: migration steps and rollback",    "role": "general","stage": 1},
        {"title": "Migrate: execute migration (batch 1)",  "role": "data",  "stage": 2},
        {"title": "Migrate: execute migration (batch 2)",  "role": "data",  "stage": 2},
        {"title": "Validate: compare source vs target",    "role": "review","stage": 3},
        {"title": "Cutover: switch traffic to new system", "role": "infra", "stage": 4},
    ],
    "infra": [
        {"title": "Plan: infrastructure changes",     "role": "infra",   "stage": 1},
        {"title": "Apply: provision resources",       "role": "infra",   "stage": 2},
        {"title": "Validate: smoke test environment", "role": "review",  "stage": 3},
    ],
    "generic_large": [
        {"title": "Phase 1: research and setup",      "role": "general", "stage": 1},
        {"title": "Phase 2: core implementation",     "role": "general", "stage": 2},
        {"title": "Phase 3: validation and cleanup",  "role": "review",  "stage": 3},
    ],
}


def pick_template(task: dict) -> str:
    text = (task.get("title","") + " " + task.get("description","")).lower()
    if any(kw in text for kw in ["etl","pipeline","glue","extract","transform","load"]):
        return "etl"
    if any(kw in text for kw in ["migrate","migration","move"]):
        return "migration"
    if any(kw in text for kw in ["feature","implement","build","add"]):
        return "feature"
    if any(kw in text for kw in ["infra","ec2","s3","terraform","provision"]):
        return "infra"
    return "generic_large"


def cmd_decompose(args):
    task, task_file = load_task(args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        return

    size     = classify_task(task)
    template = pick_template(task)
    steps    = DECOMPOSITION_TEMPLATES[template]

    parent_id = task["id"]
    subtasks  = []

    print(f"\nDecomposing [{parent_id}] {task.get('title')} ({size} → {template} template)")
    print(f"  Stages: {max(s['stage'] for s in steps)},  Subtasks: {len(steps)}\n")

    for i, step in enumerate(steps):
        sub_id = f"{parent_id}-S{i+1:02d}"
        subtask = {
            "id":           sub_id,
            "parent_id":    parent_id,
            "title":        f"[{parent_id}] {step['title']}",
            "project":      task.get("project"),
            "type":         "subtask",
            "size":         "small",
            "stage":        step["stage"],
            "assigned_role":step["role"],
            "status":       "open" if step["stage"] == 1 else "waiting",
            "priority":     task.get("priority","medium"),
            "created_at":   now_iso(),
            "updated_at":   now_iso(),
            "notes":        [],
        }
        dest = TASKS_INBOX / f"{sub_id}.json"
        dest.write_text(json.dumps(subtask, indent=2))
        subtasks.append(sub_id)
        status_str = "READY" if step["stage"] == 1 else "waiting"
        print(f"  [{sub_id}] Stage {step['stage']} | {step['role']:8s} | {status_str:8s} | {step['title']}")

    # Update parent task with decomposition info
    task["status"]      = "decomposed"
    task["subtasks"]    = subtasks
    task["template"]    = template
    task["updated_at"]  = now_iso()
    if task_file:
        task_file.write_text(json.dumps(task, indent=2))

    print(f"\n  ✓ {len(subtasks)} subtasks created. Stage-1 tasks are immediately ready.")
    print(f"  Stage-2+ tasks will unblock when their preceding stage completes.")
    print(f"\n  To dispatch: python3 scheduler.py dispatch")


# ── Dispatch ──────────────────────────────────────────────────────────────────

def cmd_dispatch(args=None):
    """
    Move ready tasks to active and print Agent-tool spawn prompts for Mayor.
    """
    import subprocess

    ready = []
    for f in sorted(TASKS_INBOX.glob("*.json")):
        t = json.loads(f.read_text())
        if t.get("status") == "open":
            ready.append((t, f))

    if not ready:
        print("No tasks ready to dispatch.")
        return

    # Get scaler recommendation
    try:
        result = subprocess.run(
            ["python3", str(ROOT / "scaler.py"), "recommend"],
            capture_output=True, text=True, cwd=ROOT
        )
        rec = json.loads(result.stdout.split("\n")[0]) if result.stdout else {}
    except Exception:
        rec = {}

    print(f"Dispatching {len(ready)} ready task(s)...\n")

    for task, f in ready:
        task_id  = task["id"]
        role     = task.get("assigned_role") or task.get("assigned_to") or "general"

        # Try to assign to existing idle worker
        try:
            result = subprocess.run(
                ["python3", str(ROOT / "scaler.py"), "assign", task_id],
                capture_output=True, text=True, cwd=ROOT
            )
            assigned_to = result.stdout.strip()
        except Exception:
            assigned_to = "NO_WORKERS_AVAILABLE"

        if "NO_WORKERS_AVAILABLE" in assigned_to:
            print(f"  [{task_id}] {task['title'][:50]}")
            print(f"    → No idle worker. Mayor should spawn new {role} worker:")
            print(f"      python3 scaler.py recommend")
        else:
            print(f"  [{task_id}] → {assigned_to}")
            # Move to active
            dest = TASKS_ACTIVE / f"{task_id}.json"
            task["status"]     = "active"
            task["updated_at"] = now_iso()
            dest.write_text(json.dumps(task, indent=2))
            f.unlink()

    if rec.get("action") == "scale_up":
        print(f"\n  ⚡ Scaler recommends: spawn {rec.get('spawn_count',1)} {rec.get('role','general')} worker(s)")
        print(f"     Reason: {rec.get('reason')}")


# ── Pipelines ─────────────────────────────────────────────────────────────────

def cmd_pipeline(args):
    sub = args.pipeline_cmd

    if sub == "create":
        pipe_id   = f"PIPE-{short_id()}"
        stages    = getattr(args, "stages", "").split(",") if getattr(args,"stages","") else []
        pipeline  = {
            "id":         pipe_id,
            "name":       args.name,
            "stages":     [{"name": s.strip(), "status": "pending", "tasks": []} for s in stages] if stages else [],
            "status":     "active",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        dest = PIPELINE_DIR / f"{pipe_id}.json"
        dest.write_text(json.dumps(pipeline, indent=2))
        print(f"✓ Pipeline {pipe_id} created: {args.name}")
        if not stages:
            print(f"  Add tasks with: python3 ngr.py tasks create --pipeline {pipe_id}")

    elif sub == "status":
        pipe_file = PIPELINE_DIR / f"{args.name}.json"
        # Try by ID or by name
        pipes = list(PIPELINE_DIR.glob("*.json"))
        found = None
        for p in pipes:
            data = json.loads(p.read_text())
            if data["id"] == args.name or data["name"] == args.name:
                found = data
                break
        if not found:
            print(f"Pipeline {args.name} not found.")
            return
        print(json.dumps(found, indent=2))

    elif sub == "list":
        pipes = list(PIPELINE_DIR.glob("*.json"))
        if not pipes:
            print("No active pipelines.")
            return
        print(f"\n{'ID':12s} {'STATUS':10s} {'NAME'}")
        print("-" * 50)
        for p in pipes:
            data = json.loads(p.read_text())
            print(f"  {data['id']:12s} {data['status']:10s} {data['name']}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(prog="scheduler", description="Task Scheduler & Decomposer")
    s = p.add_subparsers(dest="cmd")

    cp = s.add_parser("classify")
    cp.add_argument("task_id")

    dp = s.add_parser("decompose")
    dp.add_argument("task_id")

    s.add_parser("dispatch")

    pp = s.add_parser("pipeline")
    ps = pp.add_subparsers(dest="pipeline_cmd")
    pc = ps.add_parser("create")
    pc.add_argument("name")
    pc.add_argument("--stages", default="", help="Comma-separated stage names")
    pst = ps.add_parser("status")
    pst.add_argument("name")
    ps.add_parser("list")

    args = p.parse_args()
    {
        "classify":  cmd_classify,
        "decompose": cmd_decompose,
        "dispatch":  cmd_dispatch,
        "pipeline":  cmd_pipeline,
    }.get(args.cmd, lambda _: p.print_help())(args)


if __name__ == "__main__":
    main()
