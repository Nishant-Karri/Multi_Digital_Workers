"""
Deploy all 16 Multi Digital Worker agents to AWS Bedrock Agent Core.

Architecture:
  Mayor (SUPERVISOR) orchestrates 15 specialist sub-agents.
  Each sub-agent is registered as a Bedrock Agent with its CLAUDE.md as the instruction.
  Mayor uses multi-agent collaboration to route tasks based on domain/type.

Usage:
  python bedrock/deploy.py --region us-east-1
  python bedrock/deploy.py --region us-east-1 --dry-run
  python bedrock/deploy.py --region us-east-1 --agent mayor   # redeploy single agent
"""

import argparse
import json
import time
import sys
import os

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bedrock.agent_configs import AGENTS, FOUNDATION_MODEL, load_instruction

# ── IAM trust + permission policy ────────────────────────────────────────────

TRUST_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "bedrock.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
})

AGENT_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "BedrockFullAccess",
            "Effect": "Allow",
            "Action": ["bedrock:*"],
            "Resource": "*"
        }
    ]
})

ROLE_NAME   = "MDWBedrockAgentRole"
POLICY_NAME = "MDWBedrockAgentPolicy"


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    tag = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗", "STEP": "→"}.get(level, "·")
    print(f"  {tag}  {msg}")


def wait_agent_ready(client, agent_id: str, timeout: int = 120):
    """Poll until agent status is NOT_PREPARED or PREPARED (ready to use)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp   = client.get_agent(agentId=agent_id)
        status = resp["agent"]["agentStatus"]
        if status in ("NOT_PREPARED", "PREPARED"):
            return status
        if status in ("FAILED", "DELETING"):
            raise RuntimeError(f"Agent {agent_id} reached terminal status: {status}")
        log(f"Agent {agent_id} status={status}, waiting…", "STEP")
        time.sleep(5)
    raise TimeoutError(f"Agent {agent_id} not ready after {timeout}s")


def ensure_iam_role(iam, account_id: str, dry_run: bool) -> str:
    """Create or return the shared IAM role ARN for all Bedrock agents."""
    role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
    if dry_run:
        log(f"[dry-run] Would ensure IAM role: {role_arn}")
        return role_arn
    try:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        log(f"IAM role already exists: {role['Arn']} — refreshing policy")
        iam.put_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME, PolicyDocument=AGENT_POLICY)
        time.sleep(5)
        return role["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    log(f"Creating IAM role {ROLE_NAME}…", "STEP")
    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=TRUST_POLICY,
        Description="Shared execution role for all MDW Bedrock agents",
        Tags=[{"Key": "project", "Value": "multi-digital-workers"}],
    )["Role"]

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=POLICY_NAME,
        PolicyDocument=AGENT_POLICY,
    )
    log(f"Created IAM role: {role['Arn']}")
    time.sleep(10)  # IAM propagation delay
    return role["Arn"]


def get_or_create_agent(client, cfg: dict, role_arn: str, dry_run: bool) -> dict:
    """
    Create a Bedrock agent if it doesn't exist, update instruction if it does.
    Returns {agent_id, agent_name, agent_arn}.
    """
    name        = cfg["name"]
    instruction = load_instruction(cfg["id"])
    description = cfg["description"]
    is_supervisor = cfg.get("supervisor", False)

    if dry_run:
        log(f"[dry-run] Would create/update agent: {name}")
        return {"agent_id": f"dry-{cfg['id']}", "agent_name": name, "agent_arn": "arn:dry"}

    # Check if agent already exists
    paginator = client.get_paginator("list_agents")
    for page in paginator.paginate():
        for a in page.get("agentSummaries", []):
            if a["agentName"] == name:
                log(f"Agent '{name}' already exists ({a['agentId']}), updating instruction…", "STEP")
                client.update_agent(
                    agentId=a["agentId"],
                    agentName=name,
                    agentResourceRoleArn=role_arn,
                    foundationModel=FOUNDATION_MODEL,
                    description=description,
                    instruction=instruction,
                    **({"agentCollaboration": "SUPERVISOR"} if is_supervisor else {}),
                )
                wait_agent_ready(client, a["agentId"])
                return {"agent_id": a["agentId"], "agent_name": name, "agent_arn": a.get("agentArn", "")}

    # Create new agent
    kwargs = dict(
        agentName=name,
        agentResourceRoleArn=role_arn,
        foundationModel=FOUNDATION_MODEL,
        description=description,
        instruction=instruction,
        idleSessionTTLInSeconds=1800,
        tags={"project": "multi-digital-workers", "role": cfg["role"]},
    )
    if is_supervisor:
        kwargs["agentCollaboration"] = "SUPERVISOR"

    resp     = client.create_agent(**kwargs)
    agent    = resp["agent"]
    agent_id = agent["agentId"]
    log(f"Created agent '{name}' → {agent_id}")
    wait_agent_ready(client, agent_id)
    return {"agent_id": agent_id, "agent_name": name, "agent_arn": agent.get("agentArn", "")}


def ensure_alias(client, agent_id: str, agent_name: str, dry_run: bool) -> str:
    """Create or return the 'live' alias ARN for a sub-agent."""
    alias_name = "live"
    if dry_run:
        return f"arn:dry:bedrock:::agent-alias/{agent_id}/dry-alias"

    # Prepare agent first so we can create a version
    try:
        client.prepare_agent(agentId=agent_id)
        wait_agent_ready(client, agent_id)
    except ClientError as e:
        if "ConflictException" not in str(e):
            raise

    # Check existing aliases
    existing = client.list_agent_aliases(agentId=agent_id).get("agentAliasSummaries", [])
    for a in existing:
        if a["agentAliasName"] == alias_name:
            alias_arn = f"arn:aws:bedrock:{client.meta.region_name}:{boto3.client('sts').get_caller_identity()['Account']}:agent-alias/{agent_id}/{a['agentAliasId']}"
            log(f"  Alias 'live' already exists for {agent_name}: {alias_arn}")
            return alias_arn

    resp      = client.create_agent_alias(
        agentId=agent_id,
        agentAliasName=alias_name,
        description=f"Live alias for {agent_name}",
        tags={"project": "multi-digital-workers"},
    )
    alias_id  = resp["agentAlias"]["agentAliasId"]
    alias_arn = f"arn:aws:bedrock:{client.meta.region_name}:{boto3.client('sts').get_caller_identity()['Account']}:agent-alias/{agent_id}/{alias_id}"
    log(f"  Created alias 'live' for {agent_name}: {alias_arn}")
    return alias_arn


def associate_collaborators(client, mayor_id: str, sub_agents: list, dry_run: bool):
    """Register all sub-agents as collaborators under the Mayor supervisor."""
    if dry_run:
        for sa in sub_agents:
            log(f"[dry-run] Would associate collaborator: {sa['agent_name']} → mayor")
        return

    existing = {
        c["agentDescriptor"]["aliasArn"]: c
        for c in client.list_agent_collaborators(agentId=mayor_id, agentVersion="DRAFT").get("agentCollaboratorSummaries", [])
    }

    for sa in sub_agents:
        alias_arn = sa["alias_arn"]
        if alias_arn in existing:
            log(f"  Collaborator already registered: {sa['agent_name']}")
            continue
        client.associate_agent_collaborator(
            agentId=mayor_id,
            agentVersion="DRAFT",
            agentDescriptor={"aliasArn": alias_arn},
            collaboratorName=sa["agent_name"].replace("mdw-", "").replace("-", "_"),
            collaborationInstruction=sa["description"],
            relayConversationHistory="TO_COLLABORATOR",
        )
        log(f"  Associated collaborator: {sa['agent_name']}")
        time.sleep(1)


def prepare_mayor(client, mayor_id: str, dry_run: bool) -> str:
    """Prepare mayor and create its live alias."""
    if dry_run:
        return f"arn:dry:bedrock:::agent-alias/{mayor_id}/dry-mayor"
    log("Preparing Mayor agent (final step)…", "STEP")
    client.prepare_agent(agentId=mayor_id)
    wait_agent_ready(client, mayor_id, timeout=180)
    account   = boto3.client("sts").get_caller_identity()["Account"]
    region    = client.meta.region_name
    existing  = client.list_agent_aliases(agentId=mayor_id).get("agentAliasSummaries", [])
    for a in existing:
        if a["agentAliasName"] == "live":
            return f"arn:aws:bedrock:{region}:{account}:agent-alias/{mayor_id}/{a['agentAliasId']}"
    resp     = client.create_agent_alias(
        agentId=mayor_id,
        agentAliasName="live",
        description="Live alias for Mayor orchestrator",
        tags={"project": "multi-digital-workers"},
    )
    alias_id = resp["agentAlias"]["agentAliasId"]
    return f"arn:aws:bedrock:{region}:{account}:agent-alias/{mayor_id}/{alias_id}"


def save_manifest(manifest: dict, region: str):
    out_path = os.path.join(os.path.dirname(__file__), "deployed_agents.json")
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"Manifest saved → bedrock/deployed_agents.json")


# ── Main ──────────────────────────────────────────────────────────────────────

def deploy(region: str, dry_run: bool, target_agent):
    print(f"\n{'='*60}")
    print(f"  Multi Digital Workers — Bedrock Agent Core Deployment")
    print(f"  Region: {region}  |  Dry-run: {dry_run}")
    print(f"{'='*60}\n")

    session    = boto3.Session(region_name=region)
    iam        = session.client("iam")
    ba         = session.client("bedrock-agent")
    sts        = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]

    log(f"AWS account: {account_id}", "STEP")

    # Step 1 — IAM role
    print("\n[1/5] Ensuring IAM role…")
    role_arn = ensure_iam_role(iam, account_id, dry_run)

    # Step 2 — Create/update all sub-agents
    print("\n[2/5] Deploying sub-agents…")
    sub_agents_cfg = [a for a in AGENTS if not a.get("supervisor")]
    mayor_cfg      = next(a for a in AGENTS if a.get("supervisor"))

    if target_agent and target_agent != "mayor":
        sub_agents_cfg = [a for a in sub_agents_cfg if a["id"] == target_agent]

    deployed_subs = []
    for cfg in sub_agents_cfg:
        log(f"→ {cfg['name']} ({cfg['role']})", "STEP")
        info      = get_or_create_agent(ba, cfg, role_arn, dry_run)
        alias_arn = ensure_alias(ba, info["agent_id"], info["agent_name"], dry_run)
        deployed_subs.append({**info, "alias_arn": alias_arn, "description": cfg["description"]})

    # Step 3 — Create/update Mayor
    print("\n[3/5] Deploying Mayor (supervisor)…")
    if not target_agent or target_agent == "mayor":
        mayor_info = get_or_create_agent(ba, mayor_cfg, role_arn, dry_run)
        mayor_id   = mayor_info["agent_id"]
    else:
        # Load existing mayor id from manifest if redeploying single sub-agent
        manifest_path = os.path.join(os.path.dirname(__file__), "deployed_agents.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                existing = json.load(f)
            mayor_id = existing["mayor"]["agent_id"]
            mayor_info = existing["mayor"]
            log(f"Using existing Mayor: {mayor_id}")
        else:
            log("No existing Mayor found — deploying Mayor too", "WARN")
            mayor_info = get_or_create_agent(ba, mayor_cfg, role_arn, dry_run)
            mayor_id   = mayor_info["agent_id"]

    # Step 4 — Wire collaborators
    print("\n[4/5] Wiring sub-agents as Mayor collaborators…")
    associate_collaborators(ba, mayor_id, deployed_subs, dry_run)

    # Step 5 — Prepare Mayor and get entrypoint alias
    print("\n[5/5] Preparing Mayor and creating live alias…")
    mayor_alias_arn = prepare_mayor(ba, mayor_id, dry_run)
    log(f"Mayor entrypoint alias: {mayor_alias_arn}")

    # ── Save manifest ─────────────────────────────────────────────────────────
    manifest = {
        "region":     region,
        "account_id": account_id,
        "model":      FOUNDATION_MODEL,
        "mayor": {
            **mayor_info,
            "alias_arn": mayor_alias_arn,
            "entrypoint": mayor_alias_arn,
        },
        "sub_agents": {sa["agent_name"]: sa for sa in deployed_subs},
    }
    save_manifest(manifest, region)

    print(f"\n{'='*60}")
    print(f"  Deployment complete!")
    print(f"  Mayor entrypoint:  {mayor_alias_arn}")
    print(f"  Sub-agents deployed: {len(deployed_subs)}")
    print(f"{'='*60}\n")
    print("  To invoke Mayor:")
    print(f"    python bedrock/invoke.py --alias-arn {mayor_alias_arn} --prompt 'Run data quality check'")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy MDW agents to AWS Bedrock")
    parser.add_argument("--region",   default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run",  action="store_true",  help="Preview without creating resources")
    parser.add_argument("--agent",    default=None,         help="Redeploy a single agent by id")
    args = parser.parse_args()
    deploy(args.region, args.dry_run, args.agent)
