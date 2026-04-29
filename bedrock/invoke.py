"""
Invoke the Mayor agent with a natural language task.
Mayor routes to the correct sub-agent automatically.

Usage:
  python bedrock/invoke.py --prompt "Run data quality check on FACT_ORDER"
  python bedrock/invoke.py --prompt "Investigate null spike in net_sales"
  python bedrock/invoke.py --alias-arn <arn> --prompt "Deploy Terraform changes"
  python bedrock/invoke.py --list     # Show deployed agents
"""

import argparse
import json
import os
import sys
import uuid

import boto3

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "deployed_agents.json")


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        print("No deployed_agents.json found. Run: python bedrock/deploy.py first.")
        sys.exit(1)
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def invoke_agent(region: str, alias_arn: str, prompt: str, session_id):
    # Parse agent_id and alias_id from arn
    # Format: arn:aws:bedrock:<region>:<account>:agent-alias/<agentId>/<aliasId>
    parts    = alias_arn.split("/")
    agent_id = parts[-2]
    alias_id = parts[-1]
    sid      = session_id or str(uuid.uuid4())

    client = boto3.client("bedrock-agent-runtime", region_name=region)
    print(f"\n[Invoking Mayor agent]")
    print(f"  Agent:   {agent_id}")
    print(f"  Alias:   {alias_id}")
    print(f"  Session: {sid}")
    print(f"  Prompt:  {prompt}\n")
    print("-" * 60)

    resp = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=alias_id,
        sessionId=sid,
        inputText=prompt,
        enableTrace=True,
    )

    full_response = ""
    for event in resp["completion"]:
        if "chunk" in event:
            text = event["chunk"]["bytes"].decode("utf-8")
            print(text, end="", flush=True)
            full_response += text
        elif "trace" in event:
            trace = event["trace"].get("trace", {})
            # Print routing decisions so user can see which sub-agent was invoked
            if "orchestrationTrace" in trace:
                ot = trace["orchestrationTrace"]
                if "invocationInput" in ot:
                    inv = ot["invocationInput"]
                    if inv.get("invocationType") == "AGENT_COLLABORATOR":
                        collab = inv.get("agentCollaboratorInvocationInput", {})
                        print(f"\n  [Mayor → {collab.get('agentCollaboratorName','sub-agent')}]", flush=True)

    print("\n" + "-" * 60)
    return full_response


def list_agents(manifest: dict):
    print(f"\nDeployed agents (region: {manifest['region']}):\n")
    m = manifest["mayor"]
    print(f"  ★  Mayor (supervisor)")
    print(f"       agent_id:  {m['agent_id']}")
    print(f"       alias_arn: {m['alias_arn']}\n")
    for name, sa in manifest.get("sub_agents", {}).items():
        print(f"  •  {name}")
        print(f"       agent_id:  {sa['agent_id']}")
        print(f"       alias_arn: {sa['alias_arn']}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Invoke MDW Mayor agent on Bedrock")
    parser.add_argument("--prompt",    default=None, help="Task for the Mayor to execute")
    parser.add_argument("--alias-arn", default=None, help="Override Mayor alias ARN")
    parser.add_argument("--session",   default=None, help="Reuse an existing session ID")
    parser.add_argument("--list",      action="store_true", help="List deployed agents")
    args = parser.parse_args()

    manifest = load_manifest()

    if args.list:
        list_agents(manifest)
        sys.exit(0)

    if not args.prompt:
        parser.print_help()
        sys.exit(1)

    alias_arn = args.alias_arn or manifest["mayor"]["alias_arn"]
    invoke_agent(manifest["region"], alias_arn, args.prompt, args.session)
