#!/usr/bin/env python3
"""
integrations/ticket_processor.py — JIRA Ticket → MDW Task + instruction.md

Converts a JIRA ticket into:
  1. An MDW task JSON (written to tasks/inbox/)
  2. An instruction.md file (written to tasks/instructions/)
     — readable by any agent to understand exactly what to do

Usage:
  from integrations.ticket_processor import TicketProcessor
  proc = TicketProcessor()
  task_id = proc.process("DATA-123")        # fetch + create task + instruction.md
  task_id = proc.process_dict(ticket_dict)  # from already-fetched ticket
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from textwrap import indent

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TASKS_INBOX    = ROOT / "tasks" / "inbox"
INSTRUCTIONS   = ROOT / "tasks" / "instructions"

for d in [TASKS_INBOX, INSTRUCTIONS]:
    d.mkdir(parents=True, exist_ok=True)


# Priority mapping: JIRA → NGR
PRIORITY_MAP = {
    "critical":  "critical",
    "highest":   "critical",
    "high":      "high",
    "medium":    "medium",
    "low":       "low",
    "lowest":    "low",
}

# Issue type mapping: JIRA → MDW type
TYPE_MAP = {
    "bug":          "bug",
    "story":        "feature",
    "task":         "task",
    "epic":         "task",
    "sub-task":     "task",
    "improvement":  "feature",
    "new feature":  "feature",
    "incident":     "bug",
    "problem":      "bug",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:8]


class TicketProcessor:
    """
    Converts JIRA tickets to MDW tasks + instruction.md files.
    """

    def __init__(self):
        self._domain_registry   = None
        self._classify_fn       = None
        self._template_fn       = None
        self._templates_for_fn  = None
        self._routing           = None
        self._jira              = None

    # ── Lazy imports (avoid hard deps) ────────────────────────────────────

    def _load_domain(self):
        if self._classify_fn is None:
            from domains.registry import classify_task_domain, get_domain, DOMAIN_REGISTRY
            from domains.tasks    import get_template, templates_for_domain
            self._classify_fn      = classify_task_domain
            self._get_domain_fn    = get_domain
            self._domain_registry  = DOMAIN_REGISTRY
            self._template_fn      = get_template
            self._templates_for_fn = templates_for_domain

    def _load_routing(self):
        if self._routing is None:
            routing_file = ROOT / "config" / "routing.json"
            if routing_file.exists():
                self._routing = json.loads(routing_file.read_text())
            else:
                self._routing = {"rules": []}

    def _jira_client(self):
        if self._jira is None:
            from integrations.jira import JiraClient
            self._jira = JiraClient()
        return self._jira

    # ── Public API ─────────────────────────────────────────────────────────

    def process(self, ticket_key: str) -> str:
        """
        Fetch a JIRA ticket by key, create MDW task + instruction.md.
        Returns the MDW task_id.
        """
        ticket = self._jira_client().get_ticket(ticket_key)
        return self.process_dict(ticket)

    def process_dict(self, ticket: dict) -> str:
        """
        Convert an already-fetched ticket dict → MDW task + instruction.md.
        Returns the MDW task_id.
        """
        self._load_domain()
        self._load_routing()

        # Check if already synced
        existing = self._find_by_jira_key(ticket["key"])
        if existing:
            print(f"  Already synced: {ticket['key']} → {existing}")
            return existing

        # Classify domain + derive agent role
        domain      = self._classify_fn(ticket["summary"], ticket["description"])
        domain_cfg  = self._get_domain_fn(domain)
        agent_role  = domain_cfg.get("agent_role", "worker")
        templates   = self._templates_for_fn(domain)
        best_tmpl   = templates[0] if templates else None

        # Map priority + type
        priority    = PRIORITY_MAP.get(ticket["priority"].lower(), "medium")
        task_type   = TYPE_MAP.get(ticket["issue_type"].lower(), "task")

        # Auto-size task
        size        = self._size_task(ticket)

        # Build MDW task
        task_id = f"JIRA-{ticket['key']}"
        task = {
            "id":            task_id,
            "title":         ticket["summary"],
            "project":       self._infer_project(ticket),
            "type":          task_type,
            "priority":      priority,
            "size":          size,
            "status":        "open",
            "assigned_to":   agent_role,
            "created_at":    _now(),
            "updated_at":    _now(),
            "notes":         [],
            "description":   ticket["description"],
            # JIRA back-reference
            "jira_key":      ticket["key"],
            "jira_url":      ticket["url"],
            "jira_status":   ticket["status"],
            "jira_reporter": ticket["reporter"],
            "jira_labels":   ticket["labels"],
            # Domain classification
            "domain":        domain,
            "agent_role":    agent_role,
            "template":      best_tmpl,
            # Instruction file path
            "instruction_md": str(INSTRUCTIONS / f"{task_id}.md"),
        }

        # Apply routing rules
        for rule in self._routing.get("rules", []):
            m = rule.get("match", {})
            if all(task.get(k) == v for k, v in m.items()):
                task["review_required"] = rule.get("review_required", False)
                break

        # Write task
        task_file = TASKS_INBOX / f"{task_id}.json"
        task_file.write_text(json.dumps(task, indent=2, default=str))

        # Write instruction.md
        instruction = self._build_instruction(ticket, task, domain_cfg, best_tmpl)
        instr_file  = INSTRUCTIONS / f"{task_id}.md"
        instr_file.write_text(instruction)

        print(f"  ✓ {ticket['key']} → {task_id}  [{agent_role}] {ticket['summary'][:60]}")
        return task_id

    def process_bulk(self, tickets: list[dict]) -> list[str]:
        """Process a list of tickets. Returns list of task_ids."""
        task_ids = []
        for t in tickets:
            try:
                task_ids.append(self.process_dict(t))
            except Exception as e:
                print(f"  ✗ Failed to process {t.get('key','?')}: {e}")
        return task_ids

    # ── instruction.md builder ─────────────────────────────────────────────

    def _build_instruction(
        self,
        ticket:     dict,
        task:       dict,
        domain_cfg: dict,
        tmpl_name:  str,
    ) -> str:
        # Gather template stages
        stages_md = ""
        if tmpl_name and self._template_fn:
            tmpl = self._template_fn(tmpl_name)
            if tmpl.get("stages"):
                stages_md = "\n## Execution Plan\n\n"
                for i, stage in enumerate(tmpl["stages"], 1):
                    stages_md += f"### Stage {i}: {stage['name'].title()}\n\n"
                    for step in stage.get("steps", []):
                        stages_md += f"- [ ] {step}\n"
                    stages_md += "\n"

        # Comments section
        comments_md = ""
        if ticket["comments"]:
            comments_md = "\n## JIRA Comments\n\n"
            for c in ticket["comments"]:
                comments_md += f"**{c['author']}** ({c['created'][:10]}):\n{c['body']}\n\n"

        # Quality checks for this domain
        checks = domain_cfg.get("checks", [])
        checks_md = ""
        if checks:
            checks_md = "\n## Quality Gates\n\n"
            for ch in checks:
                checks_md += f"- [ ] {ch}\n"
            checks_md += "\n"

        # Platforms
        platforms = domain_cfg.get("platforms", [])
        platforms_str = ", ".join(platforms) if platforms else "—"

        # Build examples string
        examples = domain_cfg.get("examples", [])
        examples_md = ""
        if examples:
            examples_md = "\n**Similar work examples:**\n"
            for ex in examples:
                examples_md += f"- {ex}\n"

        priority_emoji = {
            "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"
        }.get(task["priority"], "⚪")

        return f"""# {task['jira_key']}: {ticket['summary']}

> **Auto-generated instruction file.** Read this before starting work.

## Ticket Details

| Field | Value |
|-------|-------|
| **JIRA Key** | [{task['jira_key']}]({ticket['url']}) |
| **Priority** | {priority_emoji} {ticket['priority']} |
| **Type** | {ticket['issue_type']} |
| **Status** | {ticket['status']} |
| **Reporter** | {ticket['reporter']} |
| **Assignee** | {ticket['assignee'] or 'Unassigned'} |
| **Labels** | {', '.join(ticket['labels']) if ticket['labels'] else '—'} |
| **Components** | {', '.join(ticket['components']) if ticket['components'] else '—'} |
| **Created** | {ticket['created'][:10]} |

## Description

{ticket['description'] or '_No description provided._'}
{comments_md}
---

## Technical Classification

| Field | Value |
|-------|-------|
| **Domain** | `{task['domain']}` |
| **Agent Role** | `{task['agent_role']}` |
| **Template** | `{task['template'] or 'none'}` |
| **Task Size** | `{task['size']}` |
| **Platforms** | {platforms_str} |
| **NGR Task ID** | `{task['id']}` |
{examples_md}
{stages_md}{checks_md}
## Definition of Done

- [ ] All execution plan stages completed
- [ ] All quality gates pass
- [ ] Code/changes reviewed (if required)
- [ ] JIRA ticket transitioned to **Done**
- [ ] MDW task marked complete: `python3 mdw.py tasks complete {task['id']} --notes "..."`
- [ ] JIRA comment added with summary of work done

## Agent Commands

```bash
# Claim this task
python3 mdw.py tasks claim {task['id']} --agent {task['agent_role']}

# View full task
python3 mdw.py tasks show {task['id']}

# Mark complete
python3 mdw.py tasks complete {task['id']} --notes "Completed: <what you did>"

# Update JIRA status
python3 mdw.py jira update {task['jira_key']} --status "In Progress"
python3 mdw.py jira update {task['jira_key']} --status "Done" --comment "Completed by MDW agent."

# Escalate if blocked
python3 mdw.py tasks block {task['id']} --reason "<reason>"
python3 mdw.py jira update {task['jira_key']} --status "Blocked"
```
"""

    # ── Helpers ────────────────────────────────────────────────────────────

    def _size_task(self, ticket: dict) -> str:
        """Estimate task size from story points, priority, and description length."""
        sp = ticket.get("story_points")
        if sp:
            if sp <= 2:   return "small"
            if sp <= 5:   return "medium"
            if sp <= 13:  return "large"
            return "epic"

        desc_len = len(ticket.get("description", ""))
        priority = ticket["priority"].lower()

        if priority == "critical":          return "large"
        if ticket["issue_type"].lower() == "epic": return "epic"
        if desc_len > 1000:                 return "large"
        if desc_len > 300:                  return "medium"
        return "small"

    def _infer_project(self, ticket: dict) -> str:
        """Map JIRA project key → MDW project id."""
        config_file = ROOT / "config" / "projects.json"
        if config_file.exists():
            cfg = json.loads(config_file.read_text())
            for p in cfg.get("projects", []):
                jira_keys = p.get("jira_projects", [])
                if ticket["key"].split("-")[0] in jira_keys:
                    return p["id"]
        # Fallback: use JIRA project key lowercased
        return ticket["key"].split("-")[0].lower()

    def _find_by_jira_key(self, jira_key: str) -> Optional[str]:
        """Check if a JIRA ticket was already synced."""
        task_id = f"JIRA-{jira_key}"
        for d in [TASKS_INBOX, ROOT / "tasks" / "active", ROOT / "tasks" / "completed"]:
            if (d / f"{task_id}.json").exists():
                return task_id
        return None
