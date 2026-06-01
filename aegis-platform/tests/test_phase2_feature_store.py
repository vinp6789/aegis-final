import ast
import importlib.util
import shutil
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
FEATURE_STORE_YAML = REPO_ROOT / "feature_store.yaml"
FEATURES_PY = REPO_ROOT / "features.py"
DB_CONFIG_YAML = WORKSPACE_ROOT / "database" / "db_config.yaml"


class Phase2StaticContractTest(unittest.TestCase):
    def test_feature_store_yaml_maps_to_phase1_database_config(self) -> None:
        config = FEATURE_STORE_YAML.read_text(encoding="utf-8")
        db_config = DB_CONFIG_YAML.read_text(encoding="utf-8")

        self.assertIn("project: aegis_platform", config)
        self.assertIn("registry: registry.db", config)
        self.assertIn("provider: local", config)
        self.assertIn("type: postgres", config)
        self.assertIn("db_schema: public", config)
        self.assertIn("password: ${AEGIS_DB_PASSWORD}", config)

        for expected in (
            "host: localhost",
            "port: 5432",
            "database: aegis",
            "user: aegis_user",
            "sslmode: prefer",
        ):
            self.assertIn(expected, config)

        for source_value in (
            "host: localhost",
            "port: 5432",
            "database: aegis",
            "username: aegis_user",
            "sslmode: prefer",
        ):
            self.assertIn(source_value, db_config)

    def test_features_python_contains_only_phase2_feature_store_objects(self) -> None:
        source = FEATURES_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assigned_names = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        self.assertIn("asset", assigned_names)
        self.assertIn("indicator", assigned_names)
        self.assertIn("daily_market_metrics", assigned_names)
        self.assertIn("macro_liquidity_indicators", assigned_names)
        self.assertIn("crypto_onchain_metrics", assigned_names)
        self.assertIn("liquidity_diagnostics", assigned_names)
        self.assertIn("market_features", assigned_names)
        self.assertIn("macro_features", assigned_names)
        self.assertIn("crypto_features", assigned_names)
        self.assertNotIn("probability_aggregator", source)
        self.assertNotIn("backtest_engine", source)
        self.assertNotIn("ingestion", source)

    def test_phase2_feature_contract_names_are_registered(self) -> None:
        source = FEATURES_PY.read_text(encoding="utf-8")

        for expected in (
            'join_keys=["asset_id"]',
            'join_keys=["indicator_code"]',
            'Field(name="open"',
            'Field(name="high"',
            'Field(name="low"',
            'Field(name="close"',
            'Field(name="volume"',
            'Field(name="market_cap"',
            'Field(name="value"',
            'Field(name="release_date"',
            'Field(name="mvrv_z_score"',
            'Field(name="ssr_ratio"',
            'Field(name="stablecoin_inflow_volume"',
            "FROM daily_market_metrics",
            'table="macro_liquidity_indicators"',
            'table="crypto_onchain_metrics"',
            'FeatureService(',
            'name="market_features"',
            'name="macro_features"',
            'name="crypto_features"',
            'name="liquidity_features"',
            'Field(name="fed_balance_sheet"',
            'Field(name="tga"',
            'Field(name="reverse_repo"',
            'Field(name="rbi_liquidity"',
            'Field(name="laf"',
            'Field(name="msf"',
            'Field(name="sdf"',
            'Field(name="fii_flows"',
            'Field(name="dii_flows"',
            '"version": "v1"',
        ):
            self.assertIn(expected, source)


@unittest.skipIf(
    importlib.util.find_spec("feast") is None,
    "Feast is not installed in this runtime.",
)
class Phase2FeastCompileTest(unittest.TestCase):
    def test_feature_definitions_import_with_feast(self) -> None:
        spec = importlib.util.spec_from_file_location("aegis_features", FEATURES_PY)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        entity_join_keys = {entity.name: entity.join_keys for entity in module.ENTITIES}
        self.assertEqual(entity_join_keys["asset"], ["asset_id"])
        self.assertEqual(entity_join_keys["indicator"], ["indicator_code"])

        feature_views = {feature_view.name: feature_view for feature_view in module.FEATURE_VIEWS}
        self.assertEqual(
            [field.name for field in feature_views["daily_market_metrics"].schema],
            ["open", "high", "low", "close", "volume", "market_cap"],
        )
        self.assertEqual(
            [field.name for field in feature_views["macro_liquidity_indicators"].schema],
            ["value", "release_date"],
        )
        self.assertEqual(
            [field.name for field in feature_views["crypto_onchain_metrics"].schema],
            ["mvrv_z_score", "ssr_ratio", "stablecoin_inflow_volume"],
        )
        self.assertTrue(all(view.tags["version"] == "v1" for view in module.FEATURE_VIEWS))
        self.assertEqual(
            [service.name for service in module.FEATURE_SERVICES],
            ["market_features", "macro_features", "crypto_features", "liquidity_features"],
        )

    def test_feast_cli_is_available_for_apply_validation(self) -> None:
        self.assertIsNotNone(shutil.which("feast"))


if __name__ == "__main__":
    unittest.main()
