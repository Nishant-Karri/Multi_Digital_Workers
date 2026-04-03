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
│   ├── mayor/CLAUDE.md    ← Mayor role (global orchestrator)
│   ├── worker/CLAUDE.md   ← Worker role (executes tasks)
│   ├── monitor/CLAUDE.md  ← Monitor role (observability)
│   └── refinery/CLAUDE.md ← Refinery role (code review/merge)
├── config/
│   ├── agents.json        ← Agent registry
│   ├── projects.json      ← Your projects
│   └── routing.json       ← Task routing rules
├── tasks/
│   ├── inbox/             ← New tasks (JSON files)
│   ├── active/            ← In-progress tasks
│   └── completed/         ← Done tasks
├── mail/                  ← Inter-agent messages
└── history/               ← Run history (JSON)
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
