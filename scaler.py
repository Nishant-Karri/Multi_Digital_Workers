#!/usr/bin/env python3
"""
scaler.py — Agent Pool Auto-Scaler

Tracks the active worker pool and provides scale-up/down decisions
for the Mayor to act on via Claude Code's Agent tool.

Usage:
  python3 scaler.py status             # Pool status + scaling recommendation
  python3 scaler.py recommend          # Print what Mayor should do now
  python3 scaler.py register <id> <role>   # Register a new worker
  python3 scaler.py heartbeat <id>         # Worker pings alive
  python3 scaler.py release <id>           # Worker finished, back to idle
  python3 scaler.py drain <id>             # Mark worker for shutdown
  python3 scaler.py reap                   # Remove dead workers
  python3 scaler.py assign <task_id>       # Find best available worker
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT        = Path(__file__).parent
POOL_FILE   = ROOT / ".runtime" / "pool.json"
CONFIG_FILE = ROOT / "config" / "scaling.json"
TASKS_INBOX  = ROOT / "tasks" / "inbox"
TASKS_ACTIVE = ROOT / "tasks" / "active"

ROOT_RUNTIME = ROOT / ".runtime"
ROOT_RUNTIME.mkdir(exist_ok=True)


def now():
    return datetime.now(timezone.utc)

def now_iso():
    return now().isoformat()

def load_config():
    return json.loads(CONFIG_FILE.read_text())

def load_pool() -> dict:
    if POOL_FILE.exists():
        return json.loads(POOL_FILE.read_text())
    return {"workers": [], "updated_at": now_iso()}

def save_pool(pool: dict):
    pool["updated_at"] = now_iso()
    POOL_FILE.write_text(json.dumps(pool, indent=2, default=str))

def queue_depth() -> int:
    return len(list(TASKS_INBOX.glob("*.json")))

def active_count() -> int:
    return len(list(TASKS_ACTIVE.glob("*.json")))

def parse_dt(s) -> datetime:
    if not s:
        return now() - timedelta(hours=999)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return now() - timedelta(hours=999)


# ── Pool Management ───────────────────────────────────────────────────────────

def cmd_status(args=None):
    pool   = load_pool()
    cfg    = load_config()["pool"]
    workers = pool.get("workers", [])

    online  = [w for w in workers if w["status"] in ("idle", "active", "draining")]
    idle    = [w for w in workers if w["status"] == "idle"]
    busy    = [w for w in workers if w["status"] == "active"]
    drain   = [w for w in workers if w["status"] == "draining"]
    qdepth  = queue_depth()

    print("=" * 55)
    print("  Agent Pool Status")
    print("=" * 55)
    print(f"  Workers online : {len(online)} / {cfg['max_workers']} max  (min: {cfg['min_workers']})")
    print(f"  Idle           : {len(idle)}")
    print(f"  Active (busy)  : {len(busy)}")
    print(f"  Draining       : {len(drain)}")
    print(f"  Queue depth    : {qdepth} tasks waiting")
    print(f"  Active tasks   : {active_count()}")
    print("=" * 55)

    if workers:
        print(f"\n  {'ID':20s} {'ROLE':10s} {'STATUS':10s} {'TASK':15s} {'UPTIME'}")
        print("  " + "-" * 70)
        for w in sorted(workers, key=lambda x: x.get("status","")):
            spawned = parse_dt(w.get("spawned_at"))
            uptime  = str(now() - spawned).split(".")[0]
            print(f"  {w['id']:20s} {w.get('role','general'):10s} {w['status']:10s} "
                  f"{(w.get('current_task') or '-'):15s} {uptime}")

    rec = _recommendation(pool, cfg, qdepth)
    if rec["action"] != "none":
        print(f"\n  ⚡ Recommendation: {rec['action'].upper()} — {rec['reason']}")
    else:
        print(f"\n  ✓ Pool is balanced.")


def cmd_recommend(args=None):
    pool  = load_pool()
    cfg   = load_config()["pool"]
    qdepth = queue_depth()
    rec   = _recommendation(pool, cfg, qdepth)

    print(json.dumps(rec, indent=2))

    if rec["action"] == "scale_up":
        print("\n── Mayor: use the Agent tool to spawn a new worker ──")
        print(_spawn_prompt(rec["role"], len(pool.get("workers", [])) + 1))
    elif rec["action"] == "scale_down":
        print(f"\n── Mayor: drain worker {rec.get('drain_id')} ──")
        print(f"  python3 scaler.py drain {rec.get('drain_id')}")


def _recommendation(pool, cfg, qdepth) -> dict:
    workers = pool.get("workers", [])
    online  = [w for w in workers if w["status"] in ("idle", "active")]
    idle    = [w for w in workers if w["status"] == "idle"]
    n       = len(online)

    # Scale up: queue is deeper than threshold * workers
    if qdepth >= cfg["scale_up_threshold"] * max(n, 1) and n < cfg["max_workers"]:
        needed = min(
            cfg["max_workers"] - n,
            max(1, qdepth // cfg["scale_up_threshold"] - n)
        )
        role = _infer_role_from_queue()
        return {
            "action": "scale_up",
            "spawn_count": needed,
            "role": role,
            "reason": f"Queue depth {qdepth} exceeds threshold ({cfg['scale_up_threshold']} × {n} workers = {cfg['scale_up_threshold']*n})",
        }

    # Scale down: idle workers beyond minimum
    if len(idle) > 0 and n > cfg["min_workers"]:
        idle_too_long = []
        cutoff = now() - timedelta(minutes=cfg["scale_down_idle_minutes"])
        for w in idle:
            idle_since = parse_dt(w.get("idle_since"))
            if idle_since < cutoff:
                idle_too_long.append(w)
        if idle_too_long:
            victim = idle_too_long[0]
            return {
                "action": "scale_down",
                "drain_id": victim["id"],
                "reason": f"Worker {victim['id']} idle > {cfg['scale_down_idle_minutes']} min, queue is low",
            }

    # Needs minimum worker
    if n < cfg["min_workers"]:
        return {
            "action": "scale_up",
            "spawn_count": cfg["min_workers"] - n,
            "role": "general",
            "reason": f"Below minimum workers ({n} < {cfg['min_workers']})",
        }

    return {"action": "none", "reason": "Pool is balanced"}


def _infer_role_from_queue() -> str:
    cfg_roles = load_config().get("worker_roles", {})
    keyword_counts = {role: 0 for role in cfg_roles}

    for f in list(TASKS_INBOX.glob("*.json"))[:20]:
        try:
            t = json.loads(f.read_text())
            title = (t.get("title", "") + " " + t.get("project", "")).lower()
            for role, rcfg in cfg_roles.items():
                if role == "general":
                    continue
                if any(kw in title for kw in rcfg.get("handles", [])):
                    keyword_counts[role] += 1
        except Exception:
            pass

    best = max(keyword_counts, key=keyword_counts.get, default="general")
    return best if keyword_counts.get(best, 0) > 0 else "general"


def cmd_register(args):
    pool = load_pool()
    worker_id = args.worker_id
    role      = getattr(args, "role", "general")

    # Check not already registered
    if any(w["id"] == worker_id for w in pool.get("workers", [])):
        print(f"Worker {worker_id} already registered.")
        return

    pool.setdefault("workers", []).append({
        "id":           worker_id,
        "role":         role,
        "status":       "idle",
        "current_task": None,
        "spawned_at":   now_iso(),
        "idle_since":   now_iso(),
        "heartbeat_at": now_iso(),
        "tasks_done":   0,
    })
    save_pool(pool)
    print(f"✓ Worker {worker_id} registered (role: {role})")


def cmd_heartbeat(args):
    pool = load_pool()
    for w in pool.get("workers", []):
        if w["id"] == args.worker_id:
            w["heartbeat_at"] = now_iso()
            save_pool(pool)
            print(f"✓ Heartbeat recorded for {args.worker_id}")
            return
    print(f"Worker {args.worker_id} not found.")


def cmd_release(args):
    pool = load_pool()
    for w in pool.get("workers", []):
        if w["id"] == args.worker_id:
            w["status"]       = "idle"
            w["current_task"] = None
            w["idle_since"]   = now_iso()
            w["heartbeat_at"] = now_iso()
            w["tasks_done"]   = w.get("tasks_done", 0) + 1
            save_pool(pool)
            print(f"✓ Worker {args.worker_id} released → idle (tasks done: {w['tasks_done']})")
            return
    print(f"Worker {args.worker_id} not found.")


def cmd_drain(args):
    pool = load_pool()
    for w in pool.get("workers", []):
        if w["id"] == args.worker_id:
            w["status"] = "draining"
            save_pool(pool)
            print(f"✓ Worker {args.worker_id} set to draining — will stop after current task.")
            return
    print(f"Worker {args.worker_id} not found.")


def cmd_reap(args=None):
    """Remove draining/dead workers from the pool."""
    pool    = load_pool()
    before  = len(pool.get("workers", []))
    cutoff  = now() - timedelta(minutes=30)

    survivors = []
    for w in pool.get("workers", []):
        hb = parse_dt(w.get("heartbeat_at"))
        if w["status"] == "draining" and w.get("current_task") is None:
            print(f"  Removed (drained):  {w['id']}")
            continue
        if hb < cutoff and w["status"] != "active":
            print(f"  Removed (dead):     {w['id']} (last heartbeat: {w.get('heartbeat_at')})")
            continue
        survivors.append(w)

    pool["workers"] = survivors
    save_pool(pool)
    removed = before - len(survivors)
    print(f"✓ Reaped {removed} worker(s). Pool size: {len(survivors)}")


def cmd_assign(args):
    """Find the best available idle worker for a task."""
    pool    = load_pool()
    task_id = args.task_id
    task    = {}

    task_file = ROOT / "tasks" / "inbox" / f"{task_id}.json"
    if task_file.exists():
        task = json.loads(task_file.read_text())

    project = (task.get("project", "") + " " + task.get("title", "")).lower()
    cfg_roles = load_config().get("worker_roles", {})

    # Find idle workers, prefer role match
    idle = [w for w in pool.get("workers", []) if w["status"] == "idle"]
    if not idle:
        print("NO_WORKERS_AVAILABLE")
        return

    def score(w):
        role_cfg = cfg_roles.get(w.get("role", "general"), {})
        handles  = role_cfg.get("handles", [])
        if "*" in handles:
            return 0
        return sum(2 for kw in handles if kw in project)

    best = max(idle, key=score)

    # Assign
    for w in pool["workers"]:
        if w["id"] == best["id"]:
            w["status"]       = "active"
            w["current_task"] = task_id
            w["heartbeat_at"] = now_iso()
            w.pop("idle_since", None)
            break

    save_pool(pool)
    print(f"✓ Assigned {task_id} → {best['id']} (role: {best.get('role')})")
    return best["id"]


def _spawn_prompt(role: str, worker_num: int) -> str:
    worker_id = f"worker-{role}-{worker_num:02d}"
    return f"""
Agent(
    subagent_type="general-purpose",
    prompt=\"\"\"
You are Worker {worker_id} in Nishant_gastown_replica.
Role specialization: {role}

Working directory: {ROOT}

STARTUP:
1. Register yourself: python3 scaler.py register {worker_id} {role}
2. Check assigned task: python3 ngr.py tasks active
3. If no task assigned, poll for work: python3 ngr.py tasks ready
4. Claim highest-priority matching task: python3 ngr.py tasks claim <task_id> --agent {worker_id}
5. Execute the task (read tasks/active/<task_id>.json for details)
6. Send heartbeat every few minutes: python3 scaler.py heartbeat {worker_id}
7. On completion: python3 ngr.py tasks complete <task_id> --notes "..."
8. Release yourself: python3 scaler.py release {worker_id}
9. Loop back to step 3 if pool says continue, else exit.

Read agents/worker/CLAUDE.md for full role instructions.
\"\"\",
    run_in_background=True
)
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(prog="scaler", description="Agent Pool Auto-Scaler")
    s = p.add_subparsers(dest="cmd")

    s.add_parser("status")
    s.add_parser("recommend")
    s.add_parser("reap")

    rp = s.add_parser("register")
    rp.add_argument("worker_id")
    rp.add_argument("role", nargs="?", default="general")

    hb = s.add_parser("heartbeat")
    hb.add_argument("worker_id")

    rel = s.add_parser("release")
    rel.add_argument("worker_id")

    dr = s.add_parser("drain")
    dr.add_argument("worker_id")

    ap = s.add_parser("assign")
    ap.add_argument("task_id")

    args = p.parse_args()
    {
        "status":    cmd_status,
        "recommend": cmd_recommend,
        "register":  cmd_register,
        "heartbeat": cmd_heartbeat,
        "release":   cmd_release,
        "drain":     cmd_drain,
        "reap":      cmd_reap,
        "assign":    cmd_assign,
    }.get(args.cmd, lambda _: p.print_help())(args)


if __name__ == "__main__":
    main()
