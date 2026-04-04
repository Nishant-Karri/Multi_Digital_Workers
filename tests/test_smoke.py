"""
tests/test_smoke.py — Fast smoke tests (no credentials needed).
Run: pytest tests/test_smoke.py -v
"""
import json
import os
import sys
import pytest

# Ensure repo root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Domain Registry ────────────────────────────────────────────────────────
class TestDomainRegistry:
    def test_import(self):
        from domains.registry import DOMAIN_REGISTRY, get_domain, classify_task_domain
        assert DOMAIN_REGISTRY

    def test_has_required_domains(self):
        from domains.registry import DOMAIN_REGISTRY
        required = ["etl_pipelines", "dbt_modelling", "data_quality",
                    "cloud_infra", "pipeline_reliability"]
        for d in required:
            assert d in DOMAIN_REGISTRY, f"Missing domain: {d}"

    def test_get_domain(self):
        from domains.registry import get_domain
        domain = get_domain("dbt_modelling")
        assert domain is not None
        assert "agent" in domain

    def test_classify_task_domain(self):
        from domains.registry import classify_task_domain
        result = classify_task_domain("build a dbt model for sales")
        assert result is not None

    def test_all_domains_have_required_fields(self):
        from domains.registry import DOMAIN_REGISTRY
        for name, d in DOMAIN_REGISTRY.items():
            assert "agent" in d, f"Domain {name} missing 'agent'"
            assert "tools" in d, f"Domain {name} missing 'tools'"


# ── Task Templates ─────────────────────────────────────────────────────────
class TestTaskTemplates:
    def test_import(self):
        from domains.tasks import TASK_TEMPLATES, get_template
        assert TASK_TEMPLATES

    def test_etl_template_has_stages(self):
        from domains.tasks import get_template
        tmpl = get_template("etl_standard")
        assert tmpl is not None
        assert "stages" in tmpl
        assert len(tmpl["stages"]) > 0

    def test_dbt_template_exists(self):
        from domains.tasks import get_template
        tmpl = get_template("dbt_model_new")
        assert tmpl is not None

    def test_all_templates_have_stages(self):
        from domains.tasks import TASK_TEMPLATES
        for name, tmpl in TASK_TEMPLATES.items():
            assert "stages" in tmpl, f"Template {name} missing 'stages'"
            for stage in tmpl["stages"]:
                assert "name" in stage, f"Stage in {name} missing 'name'"
                assert "steps" in stage, f"Stage in {name} missing 'steps'"


# ── Connector Registry ─────────────────────────────────────────────────────
class TestConnectorRegistry:
    def test_import(self):
        from connectors.registry import CONNECTOR_REGISTRY, ConnectorRegistry
        assert CONNECTOR_REGISTRY

    def test_has_required_platforms(self):
        from connectors.registry import CONNECTOR_REGISTRY
        required = ["snowflake", "s3", "aws_glue", "postgresql"]
        for p in required:
            assert p in CONNECTOR_REGISTRY, f"Missing connector: {p}"

    def test_all_connectors_have_required_fields(self):
        from connectors.registry import CONNECTOR_REGISTRY
        for name, cfg in CONNECTOR_REGISTRY.items():
            assert "vault_service" in cfg, f"Connector {name} missing vault_service"
            assert "required_keys" in cfg, f"Connector {name} missing required_keys"
            assert "factory" in cfg, f"Connector {name} missing factory"

    def test_fuzzy_match(self):
        from connectors.registry import ConnectorRegistry
        # "snow" should resolve to snowflake
        match = ConnectorRegistry._resolve("snow")
        assert match == "snowflake"


# ── Vault ──────────────────────────────────────────────────────────────────
class TestVault:
    def test_import(self):
        from vault.vault import Vault
        assert Vault

    def test_vault_instantiates(self, tmp_path):
        from vault.vault import Vault
        v = Vault(vault_dir=str(tmp_path))
        assert v is not None

    def test_set_and_get(self, tmp_path):
        from vault.vault import Vault
        v = Vault(vault_dir=str(tmp_path))
        v.set("TEST_KEY", "hello123", backend="local")
        val = v.get("TEST_KEY", backends=["local"])
        assert val == "hello123"

    def test_missing_key_returns_none(self, tmp_path):
        from vault.vault import Vault
        v = Vault(vault_dir=str(tmp_path))
        val = v.get("DOES_NOT_EXIST_XYZ", backends=["local"])
        assert val is None


# ── Config files ───────────────────────────────────────────────────────────
class TestConfigFiles:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _load(self, path):
        with open(os.path.join(self.BASE, path)) as f:
            return json.load(f)

    def test_agents_json_valid(self):
        data = self._load("config/agents.json")
        assert "agents" in data
        ids = [a["id"] for a in data["agents"]]
        for required in ["mayor", "worker", "data_engineer", "analytics_engineer",
                         "reliability", "investigator", "qa", "cicd"]:
            assert required in ids, f"Agent {required} missing from agents.json"

    def test_routing_json_valid(self):
        data = self._load("config/routing.json")
        assert "rules" in data
        assert "defaults" in data

    def test_projects_json_valid(self):
        data = self._load("config/projects.json")
        assert "projects" in data
        for proj in data["projects"]:
            assert "id" in proj
            assert "jira_projects" in proj, f"Project {proj['id']} missing jira_projects"

    def test_scaling_json_valid(self):
        data = self._load("config/scaling.json")
        assert data  # just check it loads


# ── Alert Dataclasses (no network) ────────────────────────────────────────
class TestAlerts:
    def test_severity_enum(self):
        from integrations.alerts import Severity
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.RESOLVED.value == "RESOLVED"

    def test_alert_dataclass(self):
        from integrations.alerts import Alert, Severity
        a = Alert(title="Test", body="Body", severity=Severity.HIGH, source="test")
        assert a.title == "Test"
        assert a.severity == Severity.HIGH


# ── JIRA client (no network) ──────────────────────────────────────────────
class TestJiraClient:
    def test_import(self):
        from integrations.jira import JiraClient
        assert JiraClient

    def test_adf_to_text(self):
        from integrations.jira import JiraClient
        c = JiraClient.__new__(JiraClient)
        node = {"type": "paragraph", "content": [{"type": "text", "text": "Hello world"}]}
        text = c._adf_to_text(node)
        assert "Hello world" in text

    def test_text_to_adf(self):
        from integrations.jira import JiraClient
        c = JiraClient.__new__(JiraClient)
        adf = c._text_to_adf("Line one\nLine two")
        assert adf["type"] == "doc"
        assert len(adf["content"]) >= 1
