"""dbt models as Dagster assets (dagster-dbt). Each model/snapshot/test shows up in the asset graph, wired
downstream of the ingest assets through the `raw` source tables."""

import os

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from pipeline.resources import ROOT

# dagster-dbt runs dbt from inside dbt/transitpulse, so give the local target absolute paths
os.environ.setdefault("TP_DATA_ROOT", (ROOT / "data" / "parquet").as_posix())
os.environ.setdefault("TP_DUCKDB_PATH", (ROOT / "data" / "transitpulse.duckdb").as_posix())

dbt_project = DbtProject(
    project_dir=ROOT / "dbt" / "transitpulse",
    profiles_dir=ROOT / "dbt" / "transitpulse",
    target=os.environ.get("DBT_TARGET", "local"),
)
dbt_project.prepare_if_dev()  # compiles the manifest when running `dagster dev`


class Translator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props):
        # sources map onto the ingest assets: raw.bart_od -> AssetKey(["raw", "bart_od"])
        if dbt_resource_props["resource_type"] == "source":
            if dbt_resource_props["name"] == "bart_stations":
                return AssetKey("bart_stations_raw")
            return AssetKey([dbt_resource_props["source_name"], dbt_resource_props["name"]])
        return super().get_asset_key(dbt_resource_props)

    def get_group_name(self, dbt_resource_props):
        return "warehouse"


@dbt_assets(manifest=dbt_project.manifest_path, dagster_dbt_translator=Translator())
def transitpulse_dbt(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


def dbt_resource() -> DbtCliResource:
    return DbtCliResource(project_dir=dbt_project)
