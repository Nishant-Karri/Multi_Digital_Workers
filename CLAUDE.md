# Nishant_gastown_replica — Multi-Agent Orchestrator

This is a **pure-Claude** multi-agent workspace. No external orchestrators, no custom binaries.
All orchestration uses Claude Code's built-in `Agent` tool and file-based state.

## Startup Protocol (Mayor)

Run `cat agents/mayor/CLAUDE.md` to load your full context.

```
1. Read CLAUDE.md (you are here)
2. Run: python3 ngr.py status         → See active tasks and agents
3. Run: python3 ngr.py inbox          → Check pending work
4. If tasks exist → execute them
5. If no tasks → await user instruction
```

## Architecture

```
Nishant_gastown_replica/
├── CLAUDE.md              ← Town root identity (this file)
├── ngr.py                 ← CLI: task/mail/agent management
├── agents/
│   ├── mayor/              ← Global orchestrator
│   ├── worker/             ← General task executor
│   ├── monitor/            ← Observability (data checks)
│   ├── refinery/           ← Code review / merge
│   ├── reliability/        ← Incident management, SLO, alerting  ← NEW
│   ├── data_engineer/      ← Ingestion, ETL, migration
│   ├── analytics_engineer/ ← dbt, SQL, semantic layer
│   ├── streaming_engineer/ ← Kafka, Kinesis, real-time
│   ├── data_scientist/     ← ML, features, MLOps
│   ├── analytics/          ← Dashboards, KQL, EDA
│   ├── governance/         ← Lineage, catalog, PII, RBAC
│   ├── dataops/            ← Airflow, CI/CD
│   ├── cloud_infra/        ← AWS/Azure/GCP, cost
│   └── data_quality/       ← GE, dbt tests, anomaly detection
├── integrations/
│   ├── jira.py             ← JIRA REST API client (Cloud + Server)  ← NEW
│   ├── ticket_processor.py ← JIRA ticket → task + instruction.md    ← NEW
│   ├── alerts.py           ← Teams + Slack + Outlook alerting        ← NEW
│   └── reliability.py      ← Incident management + SLO tracking      ← NEW
├── domains/
│   ├── registry.py         ← 26-domain registry (all data work)
│   └── tasks.py            ← Task templates per domain
├── connectors/
│   └── registry.py         ← ConnectorRegistry for 25 platforms
├── observability/
│   ├── observer.py         ← Freshness, row counts, nulls, schema, comparisons
│   └── config.json         ← Layer + check configuration
├── config/
│   ├── agents.json         ← Agent registry
│   ├── projects.json       ← Your projects (with jira_projects mapping)
│   ├── routing.json        ← Task routing rules
│   └── scaling.json        ← Pool + worker role config
├── vault/
│   ├── vault.py            ← 3-backend credential vault
│   └── env.template        ← All env var names (no values)
├── tasks/
│   ├── inbox/              ← New tasks (JSON files)
│   ├── active/             ← In-progress tasks
│   ├── completed/          ← Done tasks
│   └── instructions/       ← Auto-generated instruction.md per task  ← NEW
├── tasks/incidents/        ← Active + resolved incidents              ← NEW
├── mail/                   ← Inter-agent messages
└── history/                ← Run history (JSON)
```

## Multi-Agent Pattern

Mayor spawns workers using Claude Code's built-in Agent tool:

```python
# Mayor dispatches work like this:
Agent(
    subagent_type="general-purpose",
    prompt="You are a Worker. Read tasks/active/<id>.json and execute it.",
    run_in_background=True
)
```

No tmux. No Dolt. No custom binaries. **Just Claude.**

## Key Rules

- **Mayor** = orchestrator, never does implementation work directly for large tasks
- **Workers** = scoped execution, one task at a time
- **Monitor** = watches task health, reports blockers
- **Refinery** = reviews code changes before merge
- All state lives in JSON files + git commits
- Use `python3 ngr.py` for all task operations

## Projects Configured

See `config/projects.json` for all registered projects.
