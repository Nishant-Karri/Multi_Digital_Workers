"""
Delete all deployed MDW Bedrock agents and their aliases.
Reads bedrock/deployed_agents.json to know what to delete.

Usage:
  python bedrock/teardown.py
  python bedrock/teardown.py --dry-run
  python bedrock/teardown.py --agent mdw-worker   # delete single agent
"""

import argparse
import json
import os
import sys
import time

import boto3

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "deployed_agents.json")


def delete_agent(client, agent_id: str, name: str, dry_run: bool):
    if dry_run:
        print(f"  [dry-run] Would delete: {name} ({agent_id})")
        return
    # Delete aliases first
    try:
        aliases = client.list_agent_aliases(agentId=agent_id).get("agentAliasSummaries", [])
        for a in aliases:
            client.delete_agent_alias(agentId=agent_id, agentAliasId=a["agentAliasId"])
            print(f"  Deleted alias {a['agentAliasId']} for {name}")
            time.sleep(1)
    except Exception as e:
        print(f"  Warning deleting aliases for {name}: {e}")

    try:
        client.delete_agent(agentId=agent_id, skipResourceInUseCheck=True)
        print(f"  Deleted agent: {name} ({agent_id})")
    except Exception as e:
        print(f"  Error deleting {name}: {e}")
    time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Teardown MDW Bedrock agents")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent",   default=None, help="Delete only this agent name")
    args = parser.parse_args()

    if not os.path.exists(MANIFEST_PATH):
        print("No deployed_agents.json found. Nothing to tear down.")
        sys.exit(0)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    client = boto3.client("bedrock-agent", region_name=manifest["region"])

    print(f"\nTearing down MDW agents in {manifest['region']}…\n")

    # Delete sub-agents first (Mayor last)
    for name, sa in manifest.get("sub_agents", {}).items():
        if args.agent and name != args.agent:
            continue
        delete_agent(client, sa["agent_id"], name, args.dry_run)

    # Delete Mayor last (unless targeting a specific sub-agent)
    if not args.agent or args.agent == "mdw-mayor":
        m = manifest["mayor"]
        delete_agent(client, m["agent_id"], "mdw-mayor", args.dry_run)

    if not args.dry_run:
        os.remove(MANIFEST_PATH)
        print("\nManifest removed. Teardown complete.")
