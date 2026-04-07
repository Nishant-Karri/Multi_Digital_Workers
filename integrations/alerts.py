#!/usr/bin/env python3
"""
integrations/alerts.py — Unified Alerting Engine

Sends alerts to:
  - Microsoft Teams (Adaptive Cards via webhook)
  - Slack (Block Kit via webhook or Bot API)
  - Outlook / Email (SMTP or Microsoft Graph API)

Usage:
  from integrations.alerts import AlertEngine, Alert, Severity

  engine = AlertEngine()

  engine.send(Alert(
      title    = "Pipeline Failure: NWT_ORDER_FILE",
      body     = "Row count dropped 35% vs yesterday. Expected 50k, got 32k.",
      severity = Severity.HIGH,
      source   = "data_reliability",
      ticket   = "INC-42",
      links    = {"JIRA": "https://...", "Dashboard": "https://..."},
  ))
"""

import json
import os
import smtplib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Severity ──────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # total outage, data loss, P1
    HIGH     = "HIGH"       # pipeline failing, SLA breach
    MEDIUM   = "MEDIUM"     # degraded, warn threshold crossed
    LOW      = "LOW"        # informational, advisory
    RESOLVED = "RESOLVED"   # incident resolved

SEVERITY_COLORS = {
    Severity.CRITICAL: "#B91C1C",   # red-700
    Severity.HIGH:     "#EA580C",   # orange-600
    Severity.MEDIUM:   "#CA8A04",   # yellow-600
    Severity.LOW:      "#2563EB",   # blue-600
    Severity.RESOLVED: "#16A34A",   # green-600
}

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH:     "🟠",
    Severity.MEDIUM:   "🟡",
    Severity.LOW:      "🔵",
    Severity.RESOLVED: "✅",
}


# ── Alert dataclass ────────────────────────────────────────────────────────

@dataclass
class Alert:
    title:     str
    body:      str
    severity:  Severity        = Severity.HIGH
    source:    str             = "ngr"           # which agent/system sent it
    pipeline:  str             = ""              # affected pipeline name
    ticket:    str             = ""              # JIRA/INC ticket key
    links:     dict            = field(default_factory=dict)  # {"name": "url"}
    metrics:   dict            = field(default_factory=dict)  # {"row_count": 32000}
    runbook:   str             = ""              # runbook URL or path
    ts:        str             = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Credential loader ──────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _load_alert_creds() -> dict:
    return {
        "teams_webhook":   _env("NGR_TEAMS_WEBHOOK"),
        "slack_webhook":   _env("NGR_SLACK_WEBHOOK"),
        "slack_token":     _env("NGR_SLACK_BOT_TOKEN"),
        "slack_channel":   _env("NGR_SLACK_ALERT_CHANNEL", "#data-alerts"),
        "smtp_host":       _env("NGR_SMTP_HOST"),
        "smtp_port":   int(_env("NGR_SMTP_PORT", "587")),
        "smtp_user":       _env("NGR_SMTP_USER"),
        "smtp_password":   _env("NGR_SMTP_PASSWORD"),
        "smtp_from":       _env("NGR_SMTP_FROM"),
        "alert_emails":    [e.strip() for e in _env("NGR_ALERT_EMAILS", "").split(",") if e.strip()],
        # Microsoft Graph (alternative to SMTP for Outlook/O365)
        "graph_tenant":    _env("NGR_GRAPH_TENANT_ID"),
        "graph_client_id": _env("NGR_GRAPH_CLIENT_ID"),
        "graph_secret":    _env("NGR_GRAPH_CLIENT_SECRET"),
        "graph_from":      _env("NGR_GRAPH_SENDER_EMAIL"),
    }


# ── Microsoft Teams ────────────────────────────────────────────────────────

class TeamsAlerter:
    """
    Sends Adaptive Cards to a Teams channel via incoming webhook.
    Webhook URL: Teams channel → Connectors → Incoming Webhook.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        color   = SEVERITY_COLORS[alert.severity].lstrip("#")
        emoji   = SEVERITY_EMOJI[alert.severity]

        # Build facts list
        facts = [
            {"title": "Severity", "value": f"{emoji} {alert.severity}"},
            {"title": "Source",   "value": alert.source},
            {"title": "Time",     "value": alert.ts},
        ]
        if alert.pipeline:
            facts.append({"title": "Pipeline", "value": alert.pipeline})
        if alert.ticket:
            facts.append({"title": "Ticket",   "value": alert.ticket})
        for k, v in alert.metrics.items():
            facts.append({"title": k.replace("_", " ").title(), "value": str(v)})

        # Build actions (buttons)
        actions = []
        for name, url in alert.links.items():
            actions.append({
                "type":  "Action.OpenUrl",
                "title": name,
                "url":   url,
            })
        if alert.runbook:
            actions.append({
                "type":  "Action.OpenUrl",
                "title": "Runbook",
                "url":   alert.runbook,
            })

        # Adaptive Card payload
        card = {
            "type":        "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type":    "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type":   "TextBlock",
                            "size":   "Large",
                            "weight": "Bolder",
                            "text":   f"{emoji} {alert.title}",
                            "color":  self._ac_color(alert.severity),
                            "wrap":   True,
                        },
                        {
                            "type": "TextBlock",
                            "text": alert.body,
                            "wrap": True,
                        },
                        {
                            "type":   "FactSet",
                            "facts":  facts,
                        },
                    ],
                    "actions": actions,
                },
            }],
        }

        try:
            r = requests.post(self.webhook_url, json=card, timeout=10)
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"  [Teams] Send failed: {e}")
            return False

    @staticmethod
    def _ac_color(severity: Severity) -> str:
        return {
            Severity.CRITICAL: "Attention",
            Severity.HIGH:     "Warning",
            Severity.MEDIUM:   "Warning",
            Severity.LOW:      "Accent",
            Severity.RESOLVED: "Good",
        }.get(severity, "Default")


# ── Slack ──────────────────────────────────────────────────────────────────

class SlackAlerter:
    """
    Sends Block Kit messages to Slack via incoming webhook or Bot token.
    Webhook URL: api.slack.com → Your App → Incoming Webhooks
    Bot token:   api.slack.com → Your App → OAuth → Bot Token (xoxb-...)
    """

    def __init__(self, webhook_url: str = "", bot_token: str = "", channel: str = "#data-alerts"):
        self.webhook_url = webhook_url
        self.bot_token   = bot_token
        self.channel     = channel

    def send(self, alert: Alert) -> bool:
        emoji  = SEVERITY_EMOJI[alert.severity]
        color  = SEVERITY_COLORS[alert.severity]

        # Build fields
        fields = [
            {"type": "mrkdwn", "text": f"*Severity*\n{emoji} {alert.severity}"},
            {"type": "mrkdwn", "text": f"*Source*\n{alert.source}"},
            {"type": "mrkdwn", "text": f"*Time*\n{alert.ts}"},
        ]
        if alert.pipeline:
            fields.append({"type": "mrkdwn", "text": f"*Pipeline*\n{alert.pipeline}"})
        if alert.ticket:
            fields.append({"type": "mrkdwn", "text": f"*Ticket*\n{alert.ticket}"})
        for k, v in alert.metrics.items():
            fields.append({"type": "mrkdwn", "text": f"*{k.replace('_',' ').title()}*\n{v}"})

        # Build action buttons
        buttons = []
        for name, url in alert.links.items():
            buttons.append({
                "type":  "button",
                "text":  {"type": "plain_text", "text": name},
                "url":   url,
            })
        if alert.runbook:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Runbook"},
                "url":  alert.runbook,
            })

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {alert.title}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": alert.body},
            },
            {
                "type":   "section",
                "fields": fields,
            },
        ]
        if buttons:
            blocks.append({"type": "actions", "elements": buttons})
        blocks.append({"type": "divider"})

        payload = {
            "text":        f"{emoji} {alert.title}",  # fallback for notifications
            "attachments": [{
                "color":  color,
                "blocks": blocks,
            }],
        }

        try:
            if self.webhook_url:
                r = requests.post(self.webhook_url, json=payload, timeout=10)
                r.raise_for_status()
            elif self.bot_token:
                payload["channel"] = self.channel
                r = requests.post(
                    "https://slack.com/api/chat.postMessage",
                    json    = payload,
                    headers = {"Authorization": f"Bearer {self.bot_token}"},
                    timeout = 10,
                )
                r.raise_for_status()
                resp = r.json()
                if not resp.get("ok"):
                    print(f"  [Slack] API error: {resp.get('error')}")
                    return False
            else:
                print("  [Slack] No webhook_url or bot_token configured.")
                return False
            return True
        except Exception as e:
            print(f"  [Slack] Send failed: {e}")
            return False


# ── Outlook / Email ────────────────────────────────────────────────────────

class OutlookAlerter:
    """
    Sends HTML email alerts via:
    - SMTP (works with any mail server, including O365 with app password)
    - Microsoft Graph API (preferred for O365 — no legacy auth needed)
    """

    def __init__(
        self,
        smtp_host:     str = "",
        smtp_port:     int = 587,
        smtp_user:     str = "",
        smtp_password: str = "",
        smtp_from:     str = "",
        recipients:    list = None,
        # Graph API alternative
        graph_tenant:    str = "",
        graph_client_id: str = "",
        graph_secret:    str = "",
        graph_from:      str = "",
    ):
        self.smtp_host     = smtp_host
        self.smtp_port     = smtp_port
        self.smtp_user     = smtp_user
        self.smtp_password = smtp_password
        self.smtp_from     = smtp_from or smtp_user
        self.recipients    = recipients or []
        self.graph_tenant    = graph_tenant
        self.graph_client_id = graph_client_id
        self.graph_secret    = graph_secret
        self.graph_from      = graph_from

    def send(self, alert: Alert) -> bool:
        emoji    = SEVERITY_EMOJI[alert.severity]
        subject  = f"[{alert.severity}] {emoji} {alert.title}"
        html     = self._build_html(alert)

        # Try Graph API first (O365), then SMTP
        if self.graph_tenant and self.graph_client_id and self.graph_secret:
            return self._send_graph(subject, html)
        elif self.smtp_host and self.smtp_user:
            return self._send_smtp(subject, html)
        else:
            print("  [Email] No SMTP or Graph credentials configured.")
            return False

    def _build_html(self, alert: Alert) -> str:
        emoji   = SEVERITY_EMOJI[alert.severity]
        color   = SEVERITY_COLORS[alert.severity]

        metrics_rows = ""
        for k, v in alert.metrics.items():
            metrics_rows += f"<tr><td><b>{k.replace('_',' ').title()}</b></td><td>{v}</td></tr>"

        links_html = ""
        for name, url in alert.links.items():
            links_html += f'<a href="{url}" style="margin-right:12px;">{name}</a>'
        if alert.runbook:
            links_html += f'<a href="{alert.runbook}">Runbook</a>'

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">

  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="background:{color}; padding:16px 20px; border-radius:6px 6px 0 0;">
        <span style="color:white; font-size:20px; font-weight:bold;">
          {emoji} {alert.title}
        </span>
      </td>
    </tr>
    <tr>
      <td style="background:#f8f9fa; padding:16px 20px; border:1px solid #dee2e6;">

        <p style="color:#374151; font-size:15px;">{alert.body}</p>

        <table cellpadding="6" cellspacing="0" style="width:100%; border-collapse:collapse; margin:12px 0;">
          <tr style="background:#e9ecef;">
            <td><b>Severity</b></td>
            <td><span style="color:{color}; font-weight:bold;">{emoji} {alert.severity}</span></td>
          </tr>
          <tr>
            <td><b>Source</b></td><td>{alert.source}</td>
          </tr>
          <tr style="background:#e9ecef;">
            <td><b>Time</b></td><td>{alert.ts}</td>
          </tr>
          {"<tr><td><b>Pipeline</b></td><td>" + alert.pipeline + "</td></tr>" if alert.pipeline else ""}
          {"<tr style='background:#e9ecef;'><td><b>Ticket</b></td><td>" + alert.ticket + "</td></tr>" if alert.ticket else ""}
          {metrics_rows}
        </table>

        {"<p><b>Links:</b><br>" + links_html + "</p>" if links_html else ""}

      </td>
    </tr>
    <tr>
      <td style="padding:8px 20px; font-size:12px; color:#9ca3af;">
        Sent by Multi_Digital_Workers · MDW Data Reliability Agent
      </td>
    </tr>
  </table>

</body>
</html>"""

    def _send_smtp(self, subject: str, html: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = self.smtp_from
            msg["To"]      = ", ".join(self.recipients)
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_from, self.recipients, msg.as_string())
            return True
        except Exception as e:
            print(f"  [Email/SMTP] Send failed: {e}")
            return False

    def _send_graph(self, subject: str, html: str) -> bool:
        """Send via Microsoft Graph API (OAuth2 client credentials)."""
        try:
            # Get access token
            token_url = f"https://login.microsoftonline.com/{self.graph_tenant}/oauth2/v2.0/token"
            token_resp = requests.post(token_url, data={
                "grant_type":    "client_credentials",
                "client_id":     self.graph_client_id,
                "client_secret": self.graph_secret,
                "scope":         "https://graph.microsoft.com/.default",
            }, timeout=15)
            token_resp.raise_for_status()
            token = token_resp.json()["access_token"]

            # Send mail
            mail_body = {
                "message": {
                    "subject": subject,
                    "body":    {"contentType": "HTML", "content": html},
                    "toRecipients": [
                        {"emailAddress": {"address": addr}} for addr in self.recipients
                    ],
                }
            }
            send_url = f"https://graph.microsoft.com/v1.0/users/{self.graph_from}/sendMail"
            r = requests.post(
                send_url,
                json    = mail_body,
                headers = {"Authorization": f"Bearer {token}"},
                timeout = 15,
            )
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"  [Email/Graph] Send failed: {e}")
            return False


# ── AlertEngine (unified) ──────────────────────────────────────────────────

class AlertEngine:
    """
    Unified alert dispatcher. Reads config from env vars automatically.

    engine = AlertEngine()
    engine.send(Alert(title="...", body="...", severity=Severity.HIGH))
    """

    def __init__(self, creds: dict = None):
        if creds is None:
            creds = _load_alert_creds()

        self._channels: list = []

        if creds.get("teams_webhook"):
            self._channels.append(("Teams", TeamsAlerter(creds["teams_webhook"])))

        if creds.get("slack_webhook") or creds.get("slack_token"):
            self._channels.append(("Slack", SlackAlerter(
                webhook_url = creds.get("slack_webhook", ""),
                bot_token   = creds.get("slack_token", ""),
                channel     = creds.get("slack_channel", "#data-alerts"),
            )))

        if creds.get("alert_emails"):
            self._channels.append(("Email", OutlookAlerter(
                smtp_host     = creds.get("smtp_host", ""),
                smtp_port     = creds.get("smtp_port", 587),
                smtp_user     = creds.get("smtp_user", ""),
                smtp_password = creds.get("smtp_password", ""),
                smtp_from     = creds.get("smtp_from", ""),
                recipients    = creds.get("alert_emails", []),
                graph_tenant    = creds.get("graph_tenant", ""),
                graph_client_id = creds.get("graph_client_id", ""),
                graph_secret    = creds.get("graph_secret", ""),
                graph_from      = creds.get("graph_from", ""),
            )))

        if not self._channels:
            print(
                "  [AlertEngine] WARNING: No alert channels configured.\n"
                "  Set NGR_TEAMS_WEBHOOK, NGR_SLACK_WEBHOOK, or NGR_SMTP_HOST + NGR_ALERT_EMAILS."
            )

    def send(self, alert: Alert) -> dict:
        """
        Send alert to all configured channels.
        Returns {"Teams": True, "Slack": False, ...}
        """
        results = {}
        for name, channel in self._channels:
            try:
                ok = channel.send(alert)
                results[name] = ok
                status = "✓" if ok else "✗"
                print(f"  [{name}] {status} {alert.severity} — {alert.title[:60]}")
            except Exception as e:
                results[name] = False
                print(f"  [{name}] ✗ Exception: {e}")
        return results

    def send_resolved(self, title: str, body: str, ticket: str = "", **kwargs) -> dict:
        """Shorthand for sending a RESOLVED alert."""
        return self.send(Alert(
            title    = f"RESOLVED: {title}",
            body     = body,
            severity = Severity.RESOLVED,
            ticket   = ticket,
            **kwargs,
        ))

    @property
    def configured_channels(self) -> list[str]:
        return [name for name, _ in self._channels]


# ── Convenience functions ──────────────────────────────────────────────────

_default_engine: Optional[AlertEngine] = None

def get_engine() -> AlertEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = AlertEngine()
    return _default_engine

def alert(title: str, body: str, severity: Severity = Severity.HIGH, **kwargs) -> dict:
    """Shorthand: from integrations.alerts import alert; alert('title', 'body')"""
    return get_engine().send(Alert(title=title, body=body, severity=severity, **kwargs))


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Test alert sending")
    p.add_argument("--severity", default="HIGH",
                   choices=["CRITICAL","HIGH","MEDIUM","LOW","RESOLVED"])
    p.add_argument("--title",  default="Test Alert from NGR")
    p.add_argument("--body",   default="This is a test alert from the MDW alerting engine.")
    p.add_argument("--channel", choices=["teams","slack","email","all"], default="all")
    args = p.parse_args()

    creds = _load_alert_creds()
    if args.channel != "all":
        # Zero out other channels
        if args.channel != "teams": creds["teams_webhook"] = ""
        if args.channel != "slack": creds["slack_webhook"] = creds["slack_token"] = ""
        if args.channel != "email": creds["alert_emails"] = []

    engine = AlertEngine(creds)
    print(f"Configured channels: {engine.configured_channels}")
    results = engine.send(Alert(
        title    = args.title,
        body     = args.body,
        severity = Severity[args.severity],
        source   = "ngr-test",
        metrics  = {"test_metric": 42},
        links    = {"NGR Repo": "https://github.com/Nishant-Karri/Multi_Digital_Workers"},
    ))
    print(f"\nResults: {results}")
