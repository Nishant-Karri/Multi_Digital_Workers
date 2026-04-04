#!/usr/bin/env python3
"""
ngr.py — Nishant_gastown_replica CLI
Multi-agent orchestrator using Claude Teams, no external dependencies.

Usage:
  python3 ngr.py status
  python3 ngr.py tasks list [--status open|active|blocked|completed] [--project <id>]
  python3 ngr.py tasks create --title "..." --project <id> [--priority high|medium|low] [--type task|bug|feature|review]
  python3 ngr.py tasks show <task_id>
  python3 ngr.py tasks claim <task_id> [--agent <agent_id>]
  python3 ngr.py tasks complete <task_id> [--notes "..."]
  python3 ngr.py tasks block <task_id> --reason "..."
  python3 ngr.py tasks ready
  python3 ngr.py mail send <to> <message>
  python3 ngr.py mail inbox [--agent <agent_id>]
  python3 ngr.py mail read <mail_id>
  python3 ngr.py review list
  python3 ngr.py review approve <task_id> [--notes "..."]
  python3 ngr.py review reject <task_id> --notes "..."
  python3 ngr.py history [--limit 20] [--status failed]
  python3 ngr.py spawn <agent_role> --task <task_id>

  python3 ngr.py jira sync --project DATA [--status "To Do"] [--max 50]
  python3 ngr.py jira fetch DATA-123
  python3 ngr.py jira execute DATA-123
  python3 ngr.py jira update DATA-123 --status "In Progress" [--comment "..."]
  python3 ngr.py jira comment DATA-123 --text "Work started."
  python3 ngr.py jira list

  python3 ngr.py alert --title "..." --body "..." [--severity HIGH] [--pipeline <name>]
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
TASKS_INBOX   = ROOT / "tasks" / "inbox"
TASKS_ACTIVE  = ROOT / "tasks" / "active"
TASKS_DONE    = ROOT / "tasks" / "completed"
MAIL_DIR      = ROOT / "mail"
HISTORY_DIR   = ROOT / "history"
CONFIG_DIR    = ROOT / "config"

# Ensure directories exist
for d in [TASKS_INBOX, TASKS_ACTIVE, TASKS_DONE, MAIL_DIR, HISTORY_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def short_id():
    return str(uuid.uuid4())[:8]

def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def load_all(directory):
    items = []
    for f in sorted(directory.glob("*.json")):
        try:
            items.append(json.loads(f.read_text()))
        except Exception:
            pass
    return items

def load_config(name):
    return load_json(CONFIG_DIR / f"{name}.json")


# ── Status ───────────────────────────────────────────────────────────────────

def cmd_status(args):
    inbox   = list(TASKS_INBOX.glob("*.json"))
    active  = list(TASKS_ACTIVE.glob("*.json"))
    done    = list(TASKS_DONE.glob("*.json"))
    mails   = list(MAIL_DIR.glob("*.json"))

    blocked = []
    for f in active:
        t = load_json(f)
        if t.get("status") == "blocked":
            blocked.append(t)

    print("=" * 50)
    print("  Nishant_gastown_replica — Status")
    print("=" * 50)
    print(f"  Inbox (new tasks): {len(inbox)}")
    print(f"  Active tasks:      {len(active)}")
    print(f"  Blocked tasks:     {len(blocked)}")
    print(f"  Completed:         {len(done)}")
    print(f"  Unread mail:       {len([m for m in mails if not load_json(Path(MAIL_DIR/m.name)).get('read')])}")
    print("=" * 50)

    if blocked:
        print("\n  ⚠  BLOCKED:")
        for t in blocked:
            print(f"     [{t['id']}] {t['title']} — {t.get('block_reason','?')}")

    projects = load_config("projects").get("projects", [])
    print(f"\n  Projects: {len(projects)}")
    for p in projects:
        print(f"    · {p['id']:12s} {p['name']}")


# ── Tasks ────────────────────────────────────────────────────────────────────

def cmd_tasks(args):
    sub = args.tasks_cmd

    if sub == "list":
        status_filter  = getattr(args, "status", None)
        project_filter = getattr(args, "project", None)

        all_tasks = []
        dirs = {"inbox": TASKS_INBOX, "active": TASKS_ACTIVE, "completed": TASKS_DONE}
        for label, d in dirs.items():
            for t in load_all(d):
                t["_dir"] = label
                all_tasks.append(t)

        if status_filter:
            all_tasks = [t for t in all_tasks if t.get("status") == status_filter]
        if project_filter:
            all_tasks = [t for t in all_tasks if t.get("project") == project_filter]

        if not all_tasks:
            print("No tasks found.")
            return

        print(f"\n{'ID':10s} {'STATUS':10s} {'PRIORITY':8s} {'PROJECT':12s} {'TITLE'}")
        print("-" * 70)
        for t in all_tasks:
            print(f"{t.get('id','?'):10s} {t.get('status','?'):10s} {t.get('priority','medium'):8s} {t.get('project','?'):12s} {t.get('title','?')}")

    elif sub == "create":
        task_id = f"TASK-{short_id()}"
        task = {
            "id":          task_id,
            "title":       args.title,
            "project":     getattr(args, "project", "general"),
            "type":        getattr(args, "type", "task"),
            "priority":    getattr(args, "priority", "medium"),
            "status":      "open",
            "assigned_to": getattr(args, "assign", None),
            "created_at":  now_iso(),
            "updated_at":  now_iso(),
            "notes":       [],
            "description": getattr(args, "description", ""),
        }
        # Route based on config
        routing = load_config("routing")
        for rule in routing.get("rules", []):
            m = rule.get("match", {})
            if all(task.get(k) == v for k, v in m.items()):
                if not task["assigned_to"]:
                    task["assigned_to"] = rule.get("assign")
                task["review_required"] = rule.get("review_required", False)
                break

        save_json(TASKS_INBOX / f"{task_id}.json", task)
        print(f"✓ Created task {task_id}: {args.title}")
        print(f"  Project: {task['project']} | Priority: {task['priority']} | Assigned: {task['assigned_to']}")

    elif sub == "show":
        task_id = args.task_id
        for d in [TASKS_INBOX, TASKS_ACTIVE, TASKS_DONE]:
            f = d / f"{task_id}.json"
            if f.exists():
                t = load_json(f)
                print(json.dumps(t, indent=2))
                return
        print(f"Task {task_id} not found.")

    elif sub == "claim":
        task_id = args.task_id
        agent   = getattr(args, "agent", "worker")
        for d in [TASKS_INBOX, TASKS_ACTIVE]:
            f = d / f"{task_id}.json"
            if f.exists():
                t = load_json(f)
                t["status"]      = "active"
                t["assigned_to"] = agent
                t["claimed_at"]  = now_iso()
                t["updated_at"]  = now_iso()
                # Move to active if in inbox
                dest = TASKS_ACTIVE / f"{task_id}.json"
                save_json(dest, t)
                if d == TASKS_INBOX:
                    f.unlink()
                print(f"✓ Task {task_id} claimed by {agent}")
                return
        print(f"Task {task_id} not found.")

    elif sub == "complete":
        task_id = args.task_id
        notes   = getattr(args, "notes", "")
        f = TASKS_ACTIVE / f"{task_id}.json"
        if not f.exists():
            print(f"Task {task_id} not found in active.")
            return
        t = load_json(f)
        t["status"]       = "completed"
        t["completed_at"] = now_iso()
        t["updated_at"]   = now_iso()
        if notes:
            t["notes"].append({"ts": now_iso(), "text": notes})

        dest = TASKS_DONE / f"{task_id}.json"
        save_json(dest, t)
        f.unlink()

        # Append to history
        history_file = HISTORY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        history = load_json(history_file) if history_file.exists() else {"runs": []}
        history["runs"].append({
            "task_id": task_id,
            "title":   t.get("title"),
            "status":  "completed",
            "ts":      now_iso(),
        })
        save_json(history_file, history)

        print(f"✓ Task {task_id} completed.")

    elif sub == "block":
        task_id = args.task_id
        reason  = args.reason
        f = TASKS_ACTIVE / f"{task_id}.json"
        if not f.exists():
            print(f"Task {task_id} not found in active.")
            return
        t = load_json(f)
        t["status"]       = "blocked"
        t["block_reason"] = reason
        t["blocked_at"]   = now_iso()
        t["updated_at"]   = now_iso()
        save_json(f, t)
        print(f"⚠  Task {task_id} blocked: {reason}")
        print(f"   Run: python3 ngr.py mail send mayor 'BLOCKED on {task_id}: {reason}'")

    elif sub == "ready":
        tasks = load_all(TASKS_INBOX)
        ready = [t for t in tasks if t.get("status") == "open"]
        if not ready:
            print("No tasks ready to work.")
            return
        print(f"\n{'ID':10s} {'PRIORITY':8s} {'PROJECT':12s} {'TITLE'}")
        print("-" * 60)
        for t in sorted(ready, key=lambda x: {"critical":0,"high":1,"medium":2,"low":3}.get(x.get("priority","low"),3)):
            print(f"{t.get('id','?'):10s} {t.get('priority','medium'):8s} {t.get('project','?'):12s} {t.get('title','?')}")

    elif sub == "active":
        tasks = load_all(TASKS_ACTIVE)
        if not tasks:
            print("No active tasks.")
            return
        for t in tasks:
            print(f"[{t['id']}] {t['title']} — {t.get('status','active')} (assigned: {t.get('assigned_to','?')})")


# ── Mail ─────────────────────────────────────────────────────────────────────

def cmd_mail(args):
    sub = args.mail_cmd

    if sub == "send":
        mail_id = f"MAIL-{short_id()}"
        msg = {
            "id":         mail_id,
            "to":         args.to,
            "from_agent": getattr(args, "from_agent", "unknown"),
            "subject":    args.message[:60],
            "body":       args.message,
            "sent_at":    now_iso(),
            "read":       False,
        }
        save_json(MAIL_DIR / f"{mail_id}.json", msg)
        print(f"✓ Mail {mail_id} sent to {args.to}")

    elif sub == "inbox":
        agent  = getattr(args, "agent", None)
        mails  = load_all(MAIL_DIR)
        unread = [m for m in mails if not m.get("read") and (not agent or m.get("to") == agent)]
        if not unread:
            print("No unread mail.")
            return
        print(f"\n{'ID':12s} {'FROM':10s} {'SUBJECT'}")
        print("-" * 60)
        for m in sorted(unread, key=lambda x: x.get("sent_at", "")):
            print(f"{m['id']:12s} {m.get('from_agent','?'):10s} {m.get('subject','?')}")

    elif sub == "read":
        mail_id = args.mail_id
        f = MAIL_DIR / f"{mail_id}.json"
        if not f.exists():
            print(f"Mail {mail_id} not found.")
            return
        m = load_json(f)
        m["read"] = True
        save_json(f, m)
        print(f"From:    {m.get('from_agent','?')}")
        print(f"To:      {m.get('to','?')}")
        print(f"Sent:    {m.get('sent_at','?')}")
        print(f"Subject: {m.get('subject','?')}")
        print()
        print(m.get("body", ""))


# ── Review ───────────────────────────────────────────────────────────────────

def cmd_review(args):
    sub = args.review_cmd

    if sub == "list":
        tasks = load_all(TASKS_ACTIVE)
        reviews = [t for t in tasks if t.get("review_required") and t.get("status") == "active"]
        if not reviews:
            print("No pending reviews.")
            return
        for t in reviews:
            print(f"[{t['id']}] {t['title']} — by {t.get('assigned_to','?')}")

    elif sub == "approve":
        task_id = args.task_id
        notes   = getattr(args, "notes", "Approved")
        f = TASKS_ACTIVE / f"{task_id}.json"
        if f.exists():
            t = load_json(f)
            t["review_status"] = "approved"
            t["review_notes"]  = notes
            t["reviewed_at"]   = now_iso()
            save_json(f, t)
            print(f"✓ Task {task_id} approved for merge.")
        else:
            print(f"Task {task_id} not found.")

    elif sub == "reject":
        task_id = args.task_id
        notes   = args.notes
        f = TASKS_ACTIVE / f"{task_id}.json"
        if f.exists():
            t = load_json(f)
            t["review_status"] = "rejected"
            t["review_notes"]  = notes
            t["status"]        = "blocked"
            t["block_reason"]  = f"Review rejected: {notes}"
            save_json(f, t)
            print(f"✗ Task {task_id} rejected: {notes}")
        else:
            print(f"Task {task_id} not found.")


# ── History ──────────────────────────────────────────────────────────────────

def cmd_history(args):
    limit        = getattr(args, "limit", 20)
    status_filter = getattr(args, "status", None)

    all_runs = []
    for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        h = load_json(f)
        all_runs.extend(h.get("runs", []))

    if status_filter:
        all_runs = [r for r in all_runs if r.get("status") == status_filter]

    all_runs = all_runs[:limit]
    if not all_runs:
        print("No history found.")
        return

    print(f"\n{'TASK ID':12s} {'STATUS':10s} {'TITLE'}")
    print("-" * 60)
    for r in all_runs:
        print(f"{r.get('task_id','?'):12s} {r.get('status','?'):10s} {r.get('title','?')}")


# ── JIRA ─────────────────────────────────────────────────────────────────────

def cmd_jira(args):
    sub = args.jira_cmd

    if sub == "sync":
        # Fetch open tickets from JIRA and create NGR tasks + instruction.md
        from integrations.jira import JiraClient
        from integrations.ticket_processor import TicketProcessor
        client = JiraClient()
        proc   = TicketProcessor()

        project    = args.project
        status     = getattr(args, "status", None)
        max_r      = getattr(args, "max", 50)
        issue_type = getattr(args, "type", None)

        if status:
            tickets = client.get_project_tickets(project, status=status,
                                                  issue_type=issue_type, max_results=max_r)
        else:
            tickets = client.get_open_tickets(project, max_results=max_r)

        print(f"\n  Syncing {len(tickets)} tickets from {project}...\n")
        task_ids = proc.process_bulk(tickets)
        print(f"\n  ✓ Synced {len(task_ids)} tasks. Run: python3 ngr.py tasks ready")

    elif sub == "fetch":
        # Fetch and display a single JIRA ticket
        from integrations.jira import JiraClient
        client = JiraClient()
        ticket = client.get_ticket(args.ticket_key)
        print(f"\n  [{ticket['priority']}] {ticket['key']}: {ticket['summary']}")
        print(f"  Status:   {ticket['status']}")
        print(f"  Reporter: {ticket['reporter']}")
        print(f"  Labels:   {', '.join(ticket['labels']) or '—'}")
        print(f"  URL:      {ticket['url']}")
        print(f"\n  Description:\n  {ticket['description'][:500]}")

    elif sub == "execute":
        # Fetch ticket → create task + instruction.md → print agent spawn instructions
        from integrations.jira import JiraClient
        from integrations.ticket_processor import TicketProcessor
        client  = JiraClient()
        proc    = TicketProcessor()
        ticket  = client.get_ticket(args.ticket_key)
        task_id = proc.process_dict(ticket)

        # Load task to get agent role
        task_file = TASKS_INBOX / f"{task_id}.json"
        if task_file.exists():
            task = load_json(task_file)
            agent_role  = task.get("agent_role", "worker")
            domain      = task.get("domain", "—")
            instr_path  = task.get("instruction_md", "")

            print(f"\n  ✓ Task created: {task_id}")
            print(f"  Domain:  {domain}")
            print(f"  Agent:   {agent_role}")
            print(f"  Instructions: {instr_path}")
            print(f"\n  To execute, spawn the {agent_role} agent:")
            print(f"  python3 ngr.py spawn {agent_role} --task {task_id}")

            # Transition JIRA ticket to In Progress
            try:
                client.transition(args.ticket_key, "In Progress")
                client.comment(args.ticket_key, f"Picked up by NGR agent. Task ID: {task_id}")
                print(f"  ✓ JIRA {args.ticket_key} → In Progress")
            except Exception as e:
                print(f"  [JIRA] Could not transition: {e}")

    elif sub == "update":
        from integrations.jira import JiraClient
        client = JiraClient()
        if args.jira_status:
            client.transition(args.ticket_key, args.jira_status)
            print(f"  ✓ {args.ticket_key} → {args.jira_status}")
        if args.comment:
            client.comment(args.ticket_key, args.comment)
            print(f"  ✓ Comment added to {args.ticket_key}")

    elif sub == "comment":
        from integrations.jira import JiraClient
        JiraClient().comment(args.ticket_key, args.text)
        print(f"  ✓ Comment added to {args.ticket_key}")

    elif sub == "list":
        # List locally synced JIRA tasks
        all_tasks = []
        for d in [TASKS_INBOX, TASKS_ACTIVE, TASKS_DONE]:
            for f in sorted(d.glob("JIRA-*.json")):
                t = load_json(f)
                all_tasks.append(t)
        if not all_tasks:
            print("No JIRA tasks synced. Run: python3 ngr.py jira sync --project <KEY>")
            return
        print(f"\n  {'NGR ID':18s} {'JIRA':12s} {'STATUS':10s} {'PRIORITY':8s} {'TITLE'}")
        print("  " + "-" * 80)
        for t in all_tasks:
            print(
                f"  {t.get('id','?'):18s} {t.get('jira_key','?'):12s} "
                f"{t.get('status','?'):10s} {t.get('priority','?'):8s} "
                f"{t.get('title','?')[:50]}"
            )

    elif sub == "projects":
        from integrations.jira import JiraClient
        for p in JiraClient().get_projects():
            print(f"  {p['key']:10s}  {p['name']}")

    elif sub == "test":
        from integrations.jira import JiraClient
        ok = JiraClient().health_check()
        print("  ✓ JIRA connected" if ok else "  ✗ JIRA connection failed")


# ── Alert ─────────────────────────────────────────────────────────────────────

def cmd_alert(args):
    from integrations.alerts import AlertEngine, Alert, Severity
    engine = AlertEngine()
    print(f"  Channels: {engine.configured_channels}")
    engine.send(Alert(
        title    = args.title,
        body     = args.body,
        severity = Severity[args.severity.upper()],
        source   = getattr(args, "source", "ngr"),
        pipeline = getattr(args, "pipeline", ""),
        ticket   = getattr(args, "ticket", ""),
    ))


# ── Spawn (instructions for Mayor) ───────────────────────────────────────────

def cmd_spawn(args):
    """Print the Agent tool prompt Mayor should use to spawn this agent."""
    role    = args.agent_role
    task_id = getattr(args, "task", None)

    agents = {a["id"]: a for a in load_config("agents").get("agents", [])}
    agent  = agents.get(role)
    if not agent:
        print(f"Unknown agent role: {role}. Available: {list(agents.keys())}")
        return

    claude_md = ROOT / agent["claude_md"]
    print(f"""
To spawn a {role} agent, use the Agent tool in Claude Code:

Agent(
    subagent_type="general-purpose",
    prompt=\"\"\"You are a {role.capitalize()} agent in Nishant_gastown_replica.

Working directory: {ROOT}

Your role: {agent['description']}

1. Read your role file: {claude_md}
2. Run: python3 ngr.py status
{f"3. Your assigned task: python3 ngr.py tasks show {task_id}" if task_id else "3. Run: python3 ngr.py tasks ready"}
4. Execute your responsibilities.
\"\"\",
    run_in_background={"True" if role == "monitor" else "False"}
)
""")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="ngr", description="Nishant_gastown_replica CLI")
    sub = parser.add_subparsers(dest="cmd")

    # status
    sub.add_parser("status")

    # tasks
    tp = sub.add_parser("tasks")
    ts = tp.add_subparsers(dest="tasks_cmd")
    tl = ts.add_parser("list")
    tl.add_argument("--status")
    tl.add_argument("--project")
    tc = ts.add_parser("create")
    tc.add_argument("--title", required=True)
    tc.add_argument("--project", default="general")
    tc.add_argument("--priority", default="medium", choices=["critical","high","medium","low"])
    tc.add_argument("--type", default="task", choices=["task","bug","feature","review","monitor"])
    tc.add_argument("--assign")
    tc.add_argument("--description", default="")
    ts.add_parser("show").add_argument("task_id")
    cl = ts.add_parser("claim")
    cl.add_argument("task_id")
    cl.add_argument("--agent", default="worker")
    co = ts.add_parser("complete")
    co.add_argument("task_id")
    co.add_argument("--notes", default="")
    bl = ts.add_parser("block")
    bl.add_argument("task_id")
    bl.add_argument("--reason", required=True)
    ts.add_parser("ready")
    ts.add_parser("active")

    # mail
    mp = sub.add_parser("mail")
    ms = mp.add_subparsers(dest="mail_cmd")
    ms_send = ms.add_parser("send")
    ms_send.add_argument("to")
    ms_send.add_argument("message")
    ms_send.add_argument("--from-agent", dest="from_agent", default="mayor")
    mi = ms.add_parser("inbox")
    mi.add_argument("--agent")
    ms.add_parser("read").add_argument("mail_id")

    # review
    rp = sub.add_parser("review")
    rs = rp.add_subparsers(dest="review_cmd")
    rs.add_parser("list")
    ra = rs.add_parser("approve")
    ra.add_argument("task_id")
    ra.add_argument("--notes", default="Approved")
    rr = rs.add_parser("reject")
    rr.add_argument("task_id")
    rr.add_argument("--notes", required=True)

    # history
    hp = sub.add_parser("history")
    hp.add_argument("--limit", type=int, default=20)
    hp.add_argument("--status")

    # spawn
    sp = sub.add_parser("spawn")
    sp.add_argument("agent_role")
    sp.add_argument("--task")

    # jira
    jp  = sub.add_parser("jira")
    js  = jp.add_subparsers(dest="jira_cmd")

    j_sync = js.add_parser("sync")
    j_sync.add_argument("--project", required=True)
    j_sync.add_argument("--status")
    j_sync.add_argument("--type")
    j_sync.add_argument("--max", type=int, default=50)

    j_fetch = js.add_parser("fetch")
    j_fetch.add_argument("ticket_key")

    j_exec = js.add_parser("execute")
    j_exec.add_argument("ticket_key")

    j_upd = js.add_parser("update")
    j_upd.add_argument("ticket_key")
    j_upd.add_argument("--status", dest="jira_status", default="")
    j_upd.add_argument("--comment", default="")

    j_comment = js.add_parser("comment")
    j_comment.add_argument("ticket_key")
    j_comment.add_argument("--text", required=True)

    js.add_parser("list")
    js.add_parser("projects")
    js.add_parser("test")

    # alert
    alp = sub.add_parser("alert")
    alp.add_argument("--title",    required=True)
    alp.add_argument("--body",     required=True)
    alp.add_argument("--severity", default="HIGH",
                     choices=["CRITICAL","HIGH","MEDIUM","LOW","RESOLVED"])
    alp.add_argument("--pipeline", default="")
    alp.add_argument("--ticket",   default="")
    alp.add_argument("--source",   default="ngr")

    args = parser.parse_args()

    dispatch = {
        "status":  cmd_status,
        "tasks":   cmd_tasks,
        "mail":    cmd_mail,
        "review":  cmd_review,
        "history": cmd_history,
        "spawn":   cmd_spawn,
        "jira":    cmd_jira,
        "alert":   cmd_alert,
    }

    fn = dispatch.get(args.cmd)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
