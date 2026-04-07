#!/usr/bin/env python3
"""
integrations/jira.py — JIRA REST API Client

Supports JIRA Cloud (v3) and JIRA Server/Data Center (v2).
Credentials loaded from vault (service: "jira").

Vault keys required:
  base_url     — https://yourcompany.atlassian.net  (Cloud)
               or https://jira.yourcompany.com       (Server)
  user         — email (Cloud) or username (Server)
  token        — API token (Cloud) or password (Server)
  api_version  — "3" (Cloud default) or "2" (Server default)
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _load_creds() -> dict:
    base_url = os.environ.get("NGR_JIRA_BASE_URL", "").rstrip("/")
    user     = os.environ.get("NGR_JIRA_USER", "")
    token    = os.environ.get("NGR_JIRA_TOKEN", "")
    version  = os.environ.get("NGR_JIRA_API_VERSION", "3")

    if base_url and user and token:
        return {"base_url": base_url, "user": user, "token": token, "api_version": version}

    try:
        from vault.vault import Vault
        creds = Vault().get("jira") or {}
        if creds:
            return creds
    except Exception:
        pass

    raise RuntimeError(
        "JIRA credentials not found.\n"
        "Set: NGR_JIRA_BASE_URL, NGR_JIRA_USER, NGR_JIRA_TOKEN\n"
        "Or:  python3 vault/vault.py set jira '{\"base_url\":\"...\",\"user\":\"...\",\"token\":\"...\"}'"
    )


class JiraClient:
    """
    JIRA REST API client (Cloud v3 / Server v2 compatible).

    client = JiraClient()
    tickets = client.get_open_tickets("DATA")
    ticket  = client.get_ticket("DATA-123")
    client.transition("DATA-123", "In Progress")
    client.comment("DATA-123", "Work started by MDW agent.")
    """

    def __init__(self, creds: dict = None):
        if creds is None:
            creds = _load_creds()
        self.base_url    = creds["base_url"].rstrip("/")
        self.user        = creds["user"]
        self.token       = creds["token"]
        self.api_version = str(creds.get("api_version", "3"))
        self._s          = self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.auth    = HTTPBasicAuth(self.user, self.token)
        s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        return s

    def _url(self, path: str) -> str:
        return f"{self.base_url}/rest/api/{self.api_version}/{path.lstrip('/')}"

    def _get(self, path: str, params: dict = None) -> dict:
        r = self._s.get(self._url(path), params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = self._s.post(self._url(path), json=data, timeout=15)
        r.raise_for_status()
        return r.json() if r.text else {}

    def _put(self, path: str, data: dict) -> None:
        r = self._s.put(self._url(path), json=data, timeout=15)
        r.raise_for_status()

    # ── Ticket CRUD ────────────────────────────────────────────────────────

    def get_ticket(self, key: str) -> dict:
        issue = self._get(f"issue/{key}", params={
            "fields": (
                "summary,description,status,priority,assignee,reporter,"
                "labels,components,issuetype,created,updated,"
                "customfield_10014,customfield_10016,comment,subtasks,parent"
            )
        })
        return self._normalize(issue)

    def search(self, jql: str, max_results: int = 50, start_at: int = 0) -> list[dict]:
        result = self._get("search", params={
            "jql":        jql,
            "maxResults": max_results,
            "startAt":    start_at,
            "fields": (
                "summary,description,status,priority,assignee,reporter,"
                "labels,components,issuetype,created,updated,"
                "customfield_10014,customfield_10016"
            ),
        })
        return [self._normalize(i) for i in result.get("issues", [])]

    def get_open_tickets(self, project_key: str, max_results: int = 50) -> list[dict]:
        jql = (
            f'project = {project_key} '
            f'AND status NOT IN ("Done","Closed","Resolved","Cancelled") '
            f'ORDER BY priority ASC, created ASC'
        )
        return self.search(jql, max_results)

    def get_project_tickets(
        self,
        project_key: str,
        status: str = None,
        issue_type: str = None,
        assignee: str = None,
        max_results: int = 50,
    ) -> list[dict]:
        clauses = [f"project = {project_key}"]
        if status:
            clauses.append(f'status = "{status}"')
        if issue_type:
            clauses.append(f'issuetype = "{issue_type}"')
        if assignee:
            clauses.append(f'assignee = "{assignee}"')
        clauses.append("ORDER BY priority ASC, created ASC")
        return self.search(" AND ".join(clauses), max_results)

    def create_ticket(
        self,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: list = None,
        assignee_id: str = None,
    ) -> dict:
        fields = {
            "project":   {"key": project_key},
            "summary":   summary,
            "issuetype": {"name": issue_type},
            "priority":  {"name": priority},
        }
        fields["description"] = (
            _text_to_adf(description) if self.api_version == "3" else description
        )
        if labels:
            fields["labels"] = labels
        if assignee_id:
            fields["assignee"] = {"accountId": assignee_id}
        return self._post("issue", {"fields": fields})

    def comment(self, key: str, body: str) -> dict:
        payload = (
            {"body": _text_to_adf(body)} if self.api_version == "3"
            else {"body": body}
        )
        return self._post(f"issue/{key}/comment", payload)

    def transition(self, key: str, transition_name: str) -> bool:
        resp = self._get(f"issue/{key}/transitions")
        t = next(
            (t for t in resp.get("transitions", [])
             if t["name"].lower() == transition_name.lower()),
            None,
        )
        if not t:
            available = [x["name"] for x in resp.get("transitions", [])]
            raise ValueError(f"Transition '{transition_name}' not found. Available: {available}")
        self._post(f"issue/{key}/transitions", {"transition": {"id": t["id"]}})
        return True

    def update_fields(self, key: str, fields: dict) -> None:
        self._put(f"issue/{key}", {"fields": fields})

    def link_issues(self, from_key: str, to_key: str, link_type: str = "is caused by") -> None:
        """Link two issues (used by reliability agent for incident → root cause)."""
        self._post("issueLink", {
            "type":          {"name": link_type},
            "inwardIssue":   {"key": from_key},
            "outwardIssue":  {"key": to_key},
        })

    def get_projects(self) -> list[dict]:
        result = self._get("project")
        return [{"key": p["key"], "name": p["name"]} for p in (result if isinstance(result, list) else [])]

    def health_check(self) -> bool:
        try:
            self._get("myself")
            return True
        except Exception as e:
            print(f"JIRA health check failed: {e}")
            return False

    # ── Normalization ──────────────────────────────────────────────────────

    def _normalize(self, issue: dict) -> dict:
        f = issue.get("fields", {})
        comments_raw = (f.get("comment") or {}).get("comments", [])
        comments = [
            {
                "author":  _account_name(c.get("author", {})),
                "body":    _extract_text(c.get("body", "")),
                "created": c.get("created", ""),
            }
            for c in comments_raw[-5:]
        ]
        return {
            "key":          issue.get("key", ""),
            "id":           issue.get("id", ""),
            "summary":      f.get("summary", ""),
            "description":  _extract_text(f.get("description", "") or ""),
            "status":       (f.get("status") or {}).get("name", ""),
            "priority":     (f.get("priority") or {}).get("name", "Medium"),
            "issue_type":   (f.get("issuetype") or {}).get("name", "Task"),
            "assignee":     _account_name(f.get("assignee") or {}),
            "reporter":     _account_name(f.get("reporter") or {}),
            "labels":       f.get("labels", []),
            "components":   [c["name"] for c in (f.get("components") or [])],
            "created":      f.get("created", ""),
            "updated":      f.get("updated", ""),
            "story_points": f.get("customfield_10016"),
            "epic_link":    f.get("customfield_10014"),
            "subtasks":     [s.get("key") for s in (f.get("subtasks") or [])],
            "parent":       (f.get("parent") or {}).get("key"),
            "comments":     comments,
            "url":          f"{self.base_url}/browse/{issue.get('key','')}",
        }


# ── Text helpers ───────────────────────────────────────────────────────────

def _extract_text(obj) -> str:
    if not obj:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return _adf_to_text(obj).strip()
    return str(obj)


def _adf_to_text(node: dict) -> str:
    t    = node.get("type", "")
    text = node.get("text", "")
    kids = [_adf_to_text(c) for c in node.get("content", [])]
    body = "".join(kids)
    if t == "text":          return text
    if t in ("paragraph","heading"): return body.strip() + "\n"
    if t == "listItem":      return f"• {body.strip()}\n"
    if t == "codeBlock":     return f"```\n{body.strip()}\n```\n"
    if t == "hardBreak":     return "\n"
    if t == "rule":          return "---\n"
    return body


def _text_to_adf(text: str) -> dict:
    """Convert plain text to minimal ADF for JIRA Cloud v3."""
    return {
        "type":    "doc",
        "version": 1,
        "content": [{
            "type":    "paragraph",
            "content": [{"type": "text", "text": text}],
        }],
    }


def _account_name(account: dict) -> str:
    return (
        account.get("displayName") or
        account.get("name") or
        account.get("emailAddress") or ""
    )


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["test", "get", "search", "projects", "open"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--max", type=int, default=20)
    args = p.parse_args()

    c = JiraClient()
    if args.cmd == "test":
        print("✓ Connected" if c.health_check() else "✗ Failed")
    elif args.cmd == "get":
        print(json.dumps(c.get_ticket(args.arg), indent=2))
    elif args.cmd == "search":
        for t in c.search(args.arg, max_results=args.max):
            print(f"  {t['key']:12s} [{t['priority']:8s}] {t['status']:15s} {t['summary'][:60]}")
    elif args.cmd == "projects":
        for p in c.get_projects():
            print(f"  {p['key']:10s} {p['name']}")
    elif args.cmd == "open":
        for t in c.get_open_tickets(args.arg, max_results=args.max):
            print(f"  {t['key']:12s} [{t['priority']:8s}] {t['status']:15s} {t['summary'][:60]}")
