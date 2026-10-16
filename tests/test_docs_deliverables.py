"""The hand-off documents exist and say what the owner needs: the BI build guide (bi/README.md), the README's
architecture diagram and screenshots, the design backlog's v1.1 list, and the ordered owner steps
(docs/OWNER_STEPS.md)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bi_guide_present():
    text = (ROOT / "bi" / "README.md").read_text(encoding="utf-8")
    assert re.search(r"Check week: \*\*ISO week 2025-W\d{2}\*\*", text), "names the check week"
    for needle in ("Looker Studio", "Power BI", '<meta name="tp-looker-url"', "transitpulse-511002", "DAX"):
        assert needle in text, needle


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[1:4] == b"PNG" and head[12:16] == b"IHDR", f"{path.name} is a PNG"
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def test_readme_diagram_and_screenshots():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text, flags=re.S)
    assert block, "README has a mermaid diagram"
    for needle in ("BART GTFS", "Bay Wheels", "Oracle VM", "Dagster", "Spark", "dbt", "BigQuery", "Cloud Run",
                   "FastAPI", "Gemini", "Ollama", "GitHub Pages", "GitHub Actions", "WIF"):  # fmt: skip
        assert needle in block.group(1), needle
    for name, width in (("screenshot-phone.png", 390), ("screenshot-desktop.png", 1440)):
        path = ROOT / "docs" / "img" / name
        assert f"](docs/img/{name})" in text, f"README embeds {name}"
        assert _png_size(path)[0] == width, f"{name} is {width} px wide"
        assert path.stat().st_size < 600 * 1024, f"{name} is under 600 KB"


def test_design_backlog_has_v11_list():
    text = (ROOT / "docs" / "DESIGN_BACKLOG.md").read_text(encoding="utf-8")
    assert "\n## v1.1 list\n" in text
    v11 = text.split("\n## v1.1 list\n", 1)[1]
    numbers = [int(n) for n in re.findall(r"^(\d+)\. ", v11, flags=re.M)]
    assert numbers == list(range(1, len(numbers) + 1)), "numbered 1..n"
    assert len(numbers) >= 10, "the 10 open rows of the old table, at least"
    assert not re.search(r"^\|", text, flags=re.M), "no backlog row left outside the list"
    items = re.split(r"^\d+\. ", v11, flags=re.M)[1:]
    assert all("*Proposal:*" in item for item in items), "each item proposes a change"


def test_owner_steps_complete_and_ordered():
    assert "](docs/OWNER_STEPS.md)" in (ROOT / "README.md").read_text(encoding="utf-8"), "README links it"
    text = (ROOT / "docs" / "OWNER_STEPS.md").read_text(encoding="utf-8")
    needles = ("git push", "tasks.py export --api-base", "bootstrap.sh", "gcloud secrets versions add", "agent_enabled",
               "Looker Studio", "Power BI", "dbt build --target ci", "terraform plan", "Real-device", "iPhone",
               "Android", "$0", "M6")  # fmt: skip
    for needle in needles:
        assert needle in text, needle
    assert any("deploy.yml" in line and "terraform apply" in line for line in text.splitlines()), (
        "the deploy.yml decision"
    )
    first = text.index
    assert first("git push") < first("tasks.py export --api-base"), "push before the re-export"
    assert first("gcloud secrets versions add") < first("agent_enabled"), "the key before the switch"
    assert first("Looker Studio") < first("tp-looker-url"), "the dashboard before its URL"
    steps = [int(n) for n in re.findall(r"^## (\d+)\. ", text, flags=re.M)]
    assert steps == list(range(len(steps))) and len(steps) >= 14, "steps 0..13 in order"
