"""Static checks on the Cloud Run deploy code (M7): infra/terraform/*.tf (parsed with python-hcl2) and
.github/workflows/deploy.yml. Nothing here talks to GCP; `terraform validate` runs as its own check."""

import re
from pathlib import Path
from typing import Any

import hcl2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "infra" / "terraform"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
REPO = "braaaeeedyn/transitpulse"
META = {"__comments__", "__inline_comments__", "__is_block__"}


def clean(value: Any) -> Any:
    """python-hcl2 8.x keeps string quotes and comment metadata; drop both so values read like the HCL."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in META}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


@pytest.fixture(scope="module")
def tf() -> dict[str, Any]:
    """Every .tf file merged: {"resource": {type: {name: body}}, "variable": {...}, "locals": {...}}."""
    out: dict[str, Any] = {"resource": {}, "variable": {}, "locals": {}, "output": {}}
    for path in sorted(TF.glob("*.tf")):
        doc = clean(hcl2.load(path.open(encoding="utf-8")))
        for block in doc.get("resource", []):
            for rtype, named in block.items():
                out["resource"].setdefault(rtype, {}).update(named)
        for block in doc.get("variable", []):
            out["variable"].update(block)
        for block in doc.get("locals", []):
            out["locals"].update(block)
        for block in doc.get("output", []):
            out["output"].update(block)
    return out


def resources(tf: dict[str, Any], rtype: str) -> dict[str, Any]:
    return tf["resource"].get(rtype, {})


def resolve(tf: dict[str, Any], value: str) -> str:
    """Substitute variable defaults into an expression string."""
    return re.sub(r"\$\{var\.(\w+)\}", lambda m: str(tf["variable"][m.group(1)]["default"]), value).replace(
        '\\"', '"'
    )


@pytest.fixture(scope="module")
def service(tf) -> dict[str, Any]:
    (svc,) = resources(tf, "google_cloud_run_v2_service").values()
    return svc


def iam_members(tf: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(resource type, role, body) of every IAM binding in the configuration."""
    found = []
    for rtype, named in tf["resource"].items():
        if "iam" in rtype:
            for body in named.values():
                found.append((rtype, body.get("role", ""), body))
    return found


def test_cloud_run_scales_to_zero_and_caps_at_two(service):
    (template,) = service["template"]
    (scaling,) = template["scaling"]
    assert scaling["min_instance_count"] == 0
    assert scaling["max_instance_count"] == 2
    assert template["max_instance_request_concurrency"] == 80
    (container,) = template["containers"]
    (res,) = container["resources"]
    assert res["limits"] == {"cpu": "1", "memory": "512Mi"}
    assert res["cpu_idle"] is True  # billed only while serving
    assert service["location"] == "${var.region}"
    # CI owns the image; the first apply uses Google's public placeholder
    (lifecycle,) = service["lifecycle"]
    assert "${template[0].containers[0].image}" in lifecycle["ignore_changes"] or any(
        "containers[0].image" in str(x) for x in lifecycle["ignore_changes"]
    )


def test_cloud_run_runs_as_read_only_agent_sa(tf, service):
    (template,) = service["template"]
    assert template["service_account"] == '${google_service_account.sa["agent"].email}'
    # sa-agent itself is read-only: dataViewer on marts + ml, jobUser, and (only with the agent) the Gemini secret
    agent_roles = {
        (rtype, body.get("role"))
        for rtype, role, body in iam_members(tf)
        if 'sa["agent"].email' in str(body.get("member", ""))
    }
    assert agent_roles == {
        ("google_bigquery_dataset_iam_member", "roles/bigquery.dataViewer"),
        ("google_project_iam_member", "roles/bigquery.jobUser"),
        ("google_secret_manager_secret_iam_member", "roles/secretmanager.secretAccessor"),
    }
    viewer = resources(tf, "google_bigquery_dataset_iam_member")["agent_viewer"]
    assert sorted(viewer["for_each"].strip("${}").replace("toset(", "").strip("[])").split(", ")) == [
        '"marts"',
        '"ml"',
    ]


def test_only_run_invoker_is_public(tf):
    public = [
        (rtype, role)
        for rtype, role, body in iam_members(tf)
        if body.get("member") in ("allUsers", "allAuthenticatedUsers")
        or "allUsers" in str(body.get("members", ""))
    ]
    assert public == [("google_cloud_run_v2_service_iam_member", "roles/run.invoker")]
    (invoker,) = [
        b
        for b in resources(tf, "google_cloud_run_v2_service_iam_member").values()
        if b["member"] == "allUsers"
    ]
    assert invoker["name"] == "${google_cloud_run_v2_service.api.name}"  # this one service, not the project
    assert not any(
        body.get("member") == "allUsers" for body in resources(tf, "google_project_iam_member").values()
    )


def test_wif_is_pinned_to_repo_and_main(tf):
    (provider,) = resources(tf, "google_iam_workload_identity_pool_provider").values()
    (oidc,) = provider["oidc"]
    assert oidc["issuer_uri"] == "https://token.actions.githubusercontent.com"
    condition = resolve(tf, provider["attribute_condition"])
    assert condition == f'assertion.repository == "{REPO}" && assertion.ref == "refs/heads/main"'
    assert provider["attribute_mapping"]["attribute.repository"] == "assertion.repository"

    wif_users = [
        b
        for b in resources(tf, "google_service_account_iam_member").values()
        if b["role"] == "roles/iam.workloadIdentityUser"
    ]
    assert len(wif_users) == 1
    assert wif_users[0]["service_account_id"] == '${google_service_account.sa["deploy"].name}'
    assert resolve(tf, wif_users[0]["member"]).endswith(f"/attribute.repository/{REPO}")
    assert wif_users[0]["member"].startswith("principalSet://")


def test_deploy_sa_has_no_broad_roles(tf):
    deploy = sorted(
        (rtype, role)
        for rtype, role, body in iam_members(tf)
        if 'sa["deploy"].email' in str(body.get("member", ""))
    )
    assert deploy == [
        ("google_artifact_registry_repository_iam_member", "roles/artifactregistry.writer"),
        ("google_cloud_run_v2_service_iam_member", "roles/run.developer"),
        ("google_service_account_iam_member", "roles/iam.serviceAccountUser"),
    ]
    # actAs only on sa-agent, never project-wide
    (act_as,) = [
        b
        for b in resources(tf, "google_service_account_iam_member").values()
        if b["role"] == "roles/iam.serviceAccountUser"
    ]
    assert act_as["service_account_id"] == '${google_service_account.sa["agent"].name}'
    broad = {
        "roles/owner",
        "roles/editor",
        "roles/iam.securityAdmin",
        "roles/resourcemanager.projectIamAdmin",
    }
    assert not [r for _, r, _ in iam_members(tf) if r in broad]
    assert not any(
        'sa["deploy"]' in str(b.get("member", ""))
        for b in resources(tf, "google_project_iam_member").values()
    )


def test_budgets_unchanged_at_1_and_5(tf):
    (budget,) = resources(tf, "google_billing_budget").values()
    assert budget["for_each"] == {"one": 1, "five": 5}
    (amount,) = budget["amount"]
    (specified,) = amount["specified_amount"]
    assert specified["currency_code"] == "USD"
    assert specified["units"] == "${tostring(each.value)}"
    # Artifact Registry still keeps only the last 3 images (0.5 GB free tier)
    (repo,) = resources(tf, "google_artifact_registry_repository").values()
    keep = [p for p in repo["cleanup_policies"] if p["action"] == "KEEP"]
    assert keep[0]["most_recent_versions"][0]["keep_count"] == 3


def test_deploy_workflow_uses_wif_and_is_gated():
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    triggers = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert wf["permissions"] == {"contents": "read"}
    (job,) = wf["jobs"].values()
    assert job["if"].replace(" ", "") == "vars.DEPLOY_ENABLED=='true'"
    assert job["permissions"]["id-token"] == "write"
    steps = job["steps"]
    (auth,) = [s for s in steps if str(s.get("uses", "")).startswith("google-github-actions/auth@")]
    assert "workload_identity_provider" in auth["with"]
    assert "credentials_json" not in auth["with"]
    assert "credentials_json" not in text
    runs = "\n".join(s.get("run", "") for s in steps)
    # Terraform stays a human step: no terraform command and no Terraform setup action in any step
    assert not re.search(r"\bterraform\b", runs)
    assert not [s for s in steps if "terraform" in str(s.get("uses", ""))]
    assert "docker push" in runs
    assert "gcloud run deploy" in runs and "--image" in runs
    assert "GITHUB_SHA" in runs  # tag = commit SHA


def test_agent_off_by_default(tf, service):
    assert tf["variable"]["agent_enabled"]["default"] is False
    assert tf["variable"]["agent_enabled"]["type"] == "${bool}" or "bool" in str(
        tf["variable"]["agent_enabled"]["type"]
    )
    env = tf["locals"]["api_env"]
    assert "TP_AGENT_ENABLED = tostring(var.agent_enabled)" in env
    assert 'TP_WAREHOUSE = \\"bigquery\\"' in env or 'TP_WAREHOUSE = "bigquery"' in env
    assert 'TP_TRUST_PROXY = \\"true\\"' in env or 'TP_TRUST_PROXY = "true"' in env
    # the key is bound (env var + secret access) only when the agent is on, and is never a literal in Terraform
    secret_access = resources(tf, "google_secret_manager_secret_iam_member")["agent_gemini_key"]
    assert secret_access["count"] == "${var.agent_enabled ? 1 : 0}"
    (template,) = service["template"]
    (container,) = template["containers"]
    dynamic_env = [d["env"] for d in container["dynamic"]]
    key_env = [d for d in dynamic_env if "GOOGLE_API_KEY" in str(d["content"])]
    assert len(key_env) == 1 and key_env[0]["for_each"].startswith("${var.agent_enabled ?")
    assert not resources(tf, "google_secret_manager_secret_version")  # the user adds the version by hand
    assert "secretmanager.googleapis.com" in str(tf["locals"]["services"])


def test_deploy_workflow_smoke_tests_image_before_push():
    wf = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
    (job,) = wf["jobs"].values()
    runs = [str(s.get("run", "")) for s in job["steps"]]
    build = next(i for i, r in enumerate(runs) if "docker build" in r)
    smoke = next(i for i, r in enumerate(runs) if re.search(r"pytest\s+-m\s+docker", r))
    push = next(i for i, r in enumerate(runs) if "docker push" in r)
    assert build < smoke < push  # a broken image is never pushed (deploy doesn't wait for ci.yml)
    assert "TP_TEST_IMAGE" in job["steps"][smoke].get("env", {})
    assert "tests/deploy" in runs[smoke]
