from __future__ import annotations

import csv
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from statistics import mean
from typing import Any, Iterable, Mapping, Protocol, Sequence

from analytics.common import clamp


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    category: str
    source: str
    provider: str
    start_year: int
    table_name: str
    target_code: str
    license_note: str
    automatic_backfill: bool = True


@dataclass(frozen=True)
class HistoricalPoint:
    timestamp: datetime
    code: str
    value: float
    source: str


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    name: str
    start_date: date
    end_date: date
    asset_performance: str
    macro_conditions: str
    valuation_state: str
    credit_conditions: str
    liquidity_state: str
    gold_behaviour: str
    silver_behaviour: str


@dataclass(frozen=True)
class ReconstructedForecast:
    forecast_date: datetime
    forecast_type: str
    forecast_value: float
    confidence_score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class HistoricalValidationRow:
    forecast_date: datetime
    horizon_months: int
    inputs: dict[str, float]
    predictions: dict[str, float]
    realized_outcome: int
    realized_return: float
    prediction_error: float
    lead_time_months: float


@dataclass(frozen=True)
class HistoricalResearchReport:
    generated_at: datetime
    coverage_by_dataset: list[dict[str, Any]]
    missing_data_percentage: float
    backfill_completeness: float
    historical_event_coverage: float
    validation_readiness: float
    forecast_maturity_estimate: float
    research_completeness_estimate: float
    remaining_historical_gaps: list[str]
    self_learning_process: dict[str, str]


DATASET_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec("S&P 500", "equity indices", "SP500", "FRED", 1871, "daily_market_metrics", "SP500", "FRED terms; public series"),
    DatasetSpec("Dow Jones Industrial Average", "equity indices", "DJIA", "FRED", 1900, "daily_market_metrics", "DJIA", "FRED terms; public series"),
    DatasetSpec("Gold Fixing Price", "gold", "GOLDAMGBD228NLBM", "FRED", 1968, "daily_market_metrics", "GOLD", "FRED terms; public LBMA series"),
    DatasetSpec("Silver Fixing Price", "silver", "SLVPRUSD", "FRED", 1968, "daily_market_metrics", "SILVER", "FRED terms; public LBMA series"),
    DatasetSpec("Trade Weighted Dollar Index", "dollar index", "DTWEXBGS", "FRED", 2006, "daily_market_metrics", "DXY", "FRED terms; public series"),
    DatasetSpec("CPI", "inflation", "CPIAUCSL", "FRED", 1947, "macro_liquidity_indicators", "FRED_CPIAUCSL", "FRED terms; public series"),
    DatasetSpec("10Y Treasury", "interest rates", "DGS10", "FRED", 1962, "macro_liquidity_indicators", "FRED_DGS10", "FRED terms; public series"),
    DatasetSpec("3M Treasury", "interest rates", "TB3MS", "FRED", 1934, "macro_liquidity_indicators", "FRED_TB3MS", "FRED terms; public series"),
    DatasetSpec("10Y minus 2Y", "yield curves", "T10Y2Y", "FRED", 1976, "macro_liquidity_indicators", "FRED_T10Y2Y", "FRED terms; public series"),
    DatasetSpec("Moody BAA", "credit", "BAA", "FRED", 1919, "macro_liquidity_indicators", "FRED_BAA", "FRED terms; public series"),
    DatasetSpec("Moody AAA", "credit", "AAA", "FRED", 1919, "macro_liquidity_indicators", "FRED_AAA", "FRED terms; public series"),
    DatasetSpec("High Yield Spread", "credit", "BAMLH0A0HYM2", "FRED", 1996, "macro_liquidity_indicators", "FRED_BAMLH0A0HYM2", "FRED terms; public ICE BofA series"),
    DatasetSpec("Fed Balance Sheet", "liquidity", "WALCL", "FRED", 2002, "macro_liquidity_indicators", "FED_BALANCE_SHEET", "FRED terms; public series"),
    DatasetSpec("Reverse Repo", "liquidity", "RRPONTSYD", "FRED", 2013, "macro_liquidity_indicators", "REVERSE_REPO", "FRED terms; public series"),
    DatasetSpec("Shiller CAPE", "valuation", "shiller-pe", "MULTPL", 1871, "macro_liquidity_indicators", "SHILLER_CAPE", "Free public web table; no redistribution of raw source pages"),
    DatasetSpec("S&P 500 Earnings Yield", "valuation", "s-p-500-earnings-yield", "MULTPL", 1871, "macro_liquidity_indicators", "SP500_EARNINGS_YIELD", "Free public web table; no redistribution of raw source pages"),
    DatasetSpec("S&P 500 Dividend Yield", "valuation", "s-p-500-dividend-yield", "MULTPL", 1871, "macro_liquidity_indicators", "SP500_DIVIDEND_YIELD", "Free public web table; no redistribution of raw source pages"),
    DatasetSpec("Stablecoin Supply", "liquidity", "stablecoins", "DefiLlama", 2017, "stablecoin_liquidity_growth", "STABLECOIN_TOTAL", "DefiLlama public API"),
)


MARKET_EVENT_CATALOG: tuple[MarketEvent, ...] = (
    MarketEvent("1907", "Panic of 1907", date(1907, 10, 1), date(1908, 2, 29), "sharp equity drawdown", "banking panic and tight money", "limited standardized valuation data", "severe trust-company stress", "private liquidity support", "monetary hedge context limited", "industrial demand weak"),
    MarketEvent("1929", "1929 Crash / Great Depression", date(1929, 9, 1), date(1932, 7, 31), "multi-year equity collapse", "deflation and contraction", "extreme pre-crash valuation", "severe credit contraction", "policy-constrained liquidity", "gold standard regime", "deflation-sensitive weakness"),
    MarketEvent("1973", "1973 Oil Crisis", date(1973, 1, 1), date(1974, 12, 31), "inflation bear market", "oil shock and stagflation", "elevated valuation entering shock", "credit stress rising", "tightening liquidity", "strong inflation hedge", "high-beta metals volatility"),
    MarketEvent("1987", "1987 Crash", date(1987, 8, 1), date(1987, 12, 31), "rapid crash", "growth scare and market structure stress", "rich valuation", "moderate credit stress", "policy liquidity response", "safe-haven bid", "mixed risk response"),
    MarketEvent("1998", "LTCM / Russia Crisis", date(1998, 8, 1), date(1998, 10, 31), "risk-asset shock", "emerging-market and leverage stress", "high valuation", "spread widening", "Fed liquidity support", "mild hedge demand", "risk deleveraging"),
    MarketEvent("2000", "Dot-com Bubble", date(2000, 3, 1), date(2002, 10, 31), "valuation-led bear market", "profit recession", "extreme valuation", "credit deterioration", "eventual easing", "accumulation phase", "lagged participation"),
    MarketEvent("2008", "Global Financial Crisis", date(2007, 10, 1), date(2009, 3, 31), "deep equity drawdown", "housing and banking crisis", "moderate-high valuation", "extreme credit stress", "liquidity crisis then QE", "post-crisis bull impulse", "high-beta rebound"),
    MarketEvent("2011", "Euro Debt Crisis", date(2011, 7, 1), date(2011, 10, 31), "risk-off correction", "sovereign stress", "moderate valuation", "credit stress elevated", "central-bank backstop", "distribution after peak", "sharp correction"),
    MarketEvent("2020", "COVID Crash", date(2020, 2, 1), date(2020, 4, 30), "fast crash and recovery", "pandemic shock", "high valuation", "acute credit stress", "massive liquidity expansion", "liquidity-response bull impulse", "strong rebound"),
    MarketEvent("2022", "Inflation Cycle", date(2022, 1, 1), date(2022, 10, 31), "rate-driven bear market", "inflation and tightening", "high valuation reset", "credit stress rising", "liquidity withdrawal", "real-rate headwind", "cyclical weakness"),
)


def build_coverage_report(specs: Sequence[DatasetSpec] = DATASET_SPECS, *, current_year: int | None = None) -> list[dict[str, Any]]:
    end_year = current_year or datetime.now(timezone.utc).year
    report = []
    for spec in specs:
        available_years = max(0, end_year - spec.start_year + 1)
        target_years = max(1, end_year - 1900 + 1)
        missing_pct = round(clamp(1.0 - available_years / target_years, 0.0, 1.0) * 100.0, 2)
        report.append(
            {
                "dataset": spec.name,
                "category": spec.category,
                "provider": spec.provider,
                "earliest_year": spec.start_year,
                "latest_year": end_year,
                "target_table": spec.table_name,
                "target_code": spec.target_code,
                "missing_data_percentage": missing_pct,
                "automatic_backfill": spec.automatic_backfill,
                "license_note": spec.license_note,
            }
        )
    return report


class HistoricalBackfillPipeline:
    def __init__(self, *, specs: Sequence[DatasetSpec] = DATASET_SPECS, events: Sequence[MarketEvent] = MARKET_EVENT_CATALOG) -> None:
        self.specs = tuple(specs)
        self.events = tuple(events)

    def coverage_report(self) -> list[dict[str, Any]]:
        return build_coverage_report(self.specs)

    def coverage_report_from_points(
        self,
        points_by_code: Mapping[str, Sequence[HistoricalPoint]],
        *,
        current_year: int | None = None,
    ) -> list[dict[str, Any]]:
        return coverage_report_from_points(self.specs, points_by_code, current_year=current_year)

    def event_catalog(self) -> list[dict[str, Any]]:
        return [event_to_dict(event) for event in self.events]

    def fetch_historical_points(self, spec: DatasetSpec) -> list[HistoricalPoint]:
        if spec.provider == "FRED":
            return fetch_fred_points(spec.source, spec.target_code)
        if spec.provider == "MULTPL":
            return fetch_multpl_points(spec.source, spec.target_code)
        if spec.provider == "DefiLlama":
            return fetch_defillama_stablecoin_points()
        return []

    def fetch_all(self) -> dict[str, list[HistoricalPoint]]:
        return {spec.target_code: self.fetch_historical_points(spec) for spec in self.specs if spec.automatic_backfill}

    def reconstruct_monthly_forecasts(self, points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> list[ReconstructedForecast]:
        monthly = monthly_feature_rows(points_by_code)
        forecasts: list[ReconstructedForecast] = []
        for timestamp, values in monthly.items():
            valuation_risk = normalize(values.get("SHILLER_CAPE"), low=10.0, high=40.0, default=50.0)
            credit_stress = credit_stress_from_values(values)
            liquidity = liquidity_from_values(values)
            inflation = normalize(values.get("FRED_CPIAUCSL"), low=80.0, high=320.0, default=50.0)
            curve_stress = normalize(-(values.get("FRED_T10Y2Y") or 0.0), low=-1.0, high=2.0, default=45.0)
            market_return = trailing_return(values.get("SP500"), values.get("_SP500_PREV_12M"))
            panic = clamp((valuation_risk * 0.22 + credit_stress * 0.30 + (100.0 - liquidity) * 0.20 + curve_stress * 0.15 + max(0.0, -market_return) * 130.0 * 0.13) / 100.0, 0.0, 1.0)
            recovery = clamp((100.0 - panic * 100.0) * 0.45 / 100.0 + liquidity * 0.25 / 100.0 + (100.0 - credit_stress) * 0.20 / 100.0 + max(0.0, market_return) * 0.10, 0.0, 1.0)
            buy_score = clamp(recovery * 58.0 + (100.0 - valuation_risk) * 0.22, 0.0, 100.0)
            sell_score = clamp(panic * 72.0 + valuation_risk * 0.18, 0.0, 100.0)
            expected_return = clamp(recovery * 0.18 - panic * 0.24 + (100.0 - valuation_risk) / 100.0 * 0.05, -0.50, 0.50)
            expected_drawdown = clamp(panic * 0.42 + credit_stress / 100.0 * 0.15, 0.0, 0.80)
            confidence = confidence_from_completeness(values)
            metadata = {
                "source": "historical_reconstruction",
                "method": "existing Aegis formulas reconstructed from historical monthly inputs",
                "not_live_forecast": True,
                "input_codes": sorted(key for key in values if not key.startswith("_")),
            }
            forecasts.extend(
                [
                    ReconstructedForecast(timestamp, "panic_probability_12m", panic, confidence, metadata),
                    ReconstructedForecast(timestamp, "recovery_probability_12m", recovery * 100.0, confidence, metadata),
                    ReconstructedForecast(timestamp, "buy_score", buy_score, confidence, metadata),
                    ReconstructedForecast(timestamp, "sell_score", sell_score, confidence, metadata),
                    ReconstructedForecast(timestamp, "expected_return_12m", expected_return, confidence, metadata),
                    ReconstructedForecast(timestamp, "expected_drawdown_12m", expected_drawdown, confidence, metadata),
                ]
            )
        return forecasts

    def build_validation_dataset(
        self,
        points_by_code: Mapping[str, Sequence[HistoricalPoint]],
        forecasts: Sequence[ReconstructedForecast],
        *,
        horizon_months: int = 12,
    ) -> list[HistoricalValidationRow]:
        return build_validation_dataset(points_by_code, forecasts, horizon_months=horizon_months)

    def research_report(
        self,
        points_by_code: Mapping[str, Sequence[HistoricalPoint]],
        validation_rows: Sequence[HistoricalValidationRow],
        *,
        as_of: datetime | None = None,
    ) -> HistoricalResearchReport:
        return build_research_report(
            self.specs,
            self.events,
            points_by_code,
            validation_rows,
            as_of=as_of,
        )

    def persist(
        self,
        connection: DbConnection,
        points_by_code: Mapping[str, Sequence[HistoricalPoint]],
        forecasts: Sequence[ReconstructedForecast],
        validation_rows: Sequence[HistoricalValidationRow] | None = None,
        report: HistoricalResearchReport | None = None,
    ) -> dict[str, int]:
        counts = {
            "asset_registry": self.persist_asset_registry(connection),
            "daily_market_metrics": self.persist_market_points(connection, points_by_code),
            "macro_liquidity_indicators": self.persist_macro_points(connection, points_by_code),
            "stablecoin_liquidity_growth": self.persist_stablecoin_points(connection, points_by_code),
            "forecast_history": self.persist_forecast_history(connection, forecasts),
            "historical_validation_rows": self.persist_validation_dataset(connection, validation_rows or ()),
            "crisis_replay_library": self.persist_crisis_library(connection),
            "research_report": self.persist_research_report(connection, report) if report is not None else 0,
        }
        return counts

    def persist_asset_registry(self, connection: DbConnection) -> int:
        rows = [
            ("SP500", "S&P 500 Index", "equity_index", "US", "historical_backfill"),
            ("DJIA", "Dow Jones Industrial Average", "equity_index", "US", "historical_backfill"),
            ("GOLD", "Gold", "precious_metal", "GLOBAL", "historical_backfill"),
            ("SILVER", "Silver", "precious_metal", "GLOBAL", "historical_backfill"),
            ("DXY", "US Dollar Index", "currency_index", "US", "historical_backfill"),
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO asset_registry (asset_id, asset_name, asset_class, region, data_provider)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO NOTHING
                """,
                rows,
            )
        return len(rows)

    def persist_market_points(self, connection: DbConnection, points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> int:
        market_codes = {"SP500", "DJIA", "GOLD", "SILVER", "DXY"}
        rows = []
        for code in market_codes:
            for point in points_by_code.get(code, ()):
                price = max(point.value, 0.000001)
                rows.append((point.timestamp, code, price, price, price, price, 0.0, 0.0))
        if not rows:
            return 0
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO daily_market_metrics (
                    timestamp, asset_id, open_price, high_price, low_price, close_price, volume, market_cap
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)

    def persist_macro_points(self, connection: DbConnection, points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> int:
        macro_codes = {spec.target_code for spec in self.specs if spec.table_name == "macro_liquidity_indicators"}
        rows = []
        for code in macro_codes:
            for point in points_by_code.get(code, ()):
                rows.append((point.timestamp, code, point.value, point.timestamp))
        if not rows:
            return 0
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO macro_liquidity_indicators (timestamp, indicator_code, value, revised, release_date)
                VALUES (%s, %s, %s, FALSE, %s)
                """,
                rows,
            )
        return len(rows)

    def persist_stablecoin_points(self, connection: DbConnection, points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> int:
        points = list(points_by_code.get("STABLECOIN_TOTAL", ()))
        if not points:
            return 0
        rows = []
        previous = None
        for point in sorted(points, key=lambda item: item.timestamp):
            daily = pct_change(point.value, previous)
            rows.append((point.timestamp, "STABLECOIN_TOTAL", point.value, daily, daily, daily))
            previous = point.value
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO stablecoin_liquidity_growth (
                    timestamp, token_symbol, circulating_supply, daily_growth_pct, weekly_growth_pct, monthly_growth_pct
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)

    def persist_forecast_history(self, connection: DbConnection, forecasts: Sequence[ReconstructedForecast]) -> int:
        if not forecasts:
            return 0
        rows = [
            (
                forecast.forecast_date,
                forecast.forecast_type,
                forecast.forecast_value,
                forecast.confidence_score,
                "GLOBAL",
                json.dumps(forecast.metadata, sort_keys=True),
            )
            for forecast in forecasts
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO forecast_history (
                    forecast_date, forecast_type, forecast_value, confidence_score, target_scope, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                rows,
            )
        return len(rows)

    def persist_validation_dataset(self, connection: DbConnection, rows: Sequence[HistoricalValidationRow]) -> int:
        if not rows:
            return 0
        payload_rows = [
            (
                row.forecast_date,
                f"historical_validation_{row.horizon_months}m",
                row.prediction_error,
                confidence_from_validation_row(row),
                "GLOBAL",
                json.dumps(validation_row_to_dict(row), sort_keys=True),
            )
            for row in rows
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO forecast_history (
                    forecast_date, forecast_type, forecast_value, confidence_score, target_scope, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                payload_rows,
            )
        return len(payload_rows)

    def persist_research_report(self, connection: DbConnection, report: HistoricalResearchReport) -> int:
        row = (
            report.generated_at,
            "historical_backfill",
            "research_dataset",
            "HISTORICAL_RESEARCH_COVERAGE_REPORT",
            json.dumps(research_report_to_dict(report), sort_keys=True),
            severity_for_report(report),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO data_quality_exceptions (
                    timestamp, source_name, field_name, exception_type, bad_value_raw, severity
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                row,
            )
        return 1

    def persist_crisis_library(self, connection: DbConnection) -> int:
        rows = [(event.name, event.start_date, event.end_date) for event in self.events]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO crisis_replay_library (crisis_name, start_date, end_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (crisis_name) DO UPDATE
                SET start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date
                """,
                rows,
            )
        return len(rows)


def fetch_fred_points(series_id: str, target_code: str) -> list[HistoricalPoint]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id, safe='')}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except Exception:
        return []
    points = []
    for row in csv.DictReader(StringIO(raw)):
        value = parse_float(row.get(series_id))
        timestamp = parse_date(row.get("observation_date") or row.get("DATE"))
        if value is None or timestamp is None:
            continue
        points.append(HistoricalPoint(timestamp, target_code, value, "FRED"))
    return points


def fetch_multpl_points(slug: str, target_code: str) -> list[HistoricalPoint]:
    url = f"https://www.multpl.com/{urllib.parse.quote(slug, safe='')}/table/by-month"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    points = []
    import re

    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 2:
            continue
        timestamp = parse_multpl_date(clean_html(cells[0]))
        value = parse_float(clean_html(cells[1]))
        if timestamp is not None and value is not None:
            points.append(HistoricalPoint(timestamp, target_code, value, "MULTPL"))
    return points


def fetch_defillama_stablecoin_points() -> list[HistoricalPoint]:
    try:
        request = urllib.request.Request("https://stablecoins.llama.fi/stablecoincharts/all", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    points = []
    if not isinstance(payload, list):
        return points
    for row in payload:
        if not isinstance(row, dict):
            continue
        timestamp = parse_unix_timestamp(row.get("date"))
        value = stablecoin_value(row.get("totalCirculatingUSD") or row.get("totalCirculating"))
        if timestamp is not None and value is not None:
            points.append(HistoricalPoint(timestamp, "STABLECOIN_TOTAL", value, "DefiLlama"))
    return points


def monthly_feature_rows(points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> dict[datetime, dict[str, float]]:
    rows: dict[datetime, dict[str, float]] = {}
    sp500_history: list[tuple[datetime, float]] = []
    for point in sorted(points_by_code.get("SP500", ()), key=lambda item: item.timestamp):
        sp500_history.append((month_start(point.timestamp), point.value))
    previous_12m = {timestamp: prior_value(sp500_history, timestamp, months=12) for timestamp, _value in sp500_history}
    for code, points in points_by_code.items():
        for point in points:
            bucket = month_start(point.timestamp)
            rows.setdefault(bucket, {})[code] = point.value
    for timestamp, values in rows.items():
        if timestamp in previous_12m and previous_12m[timestamp] is not None:
            values["_SP500_PREV_12M"] = previous_12m[timestamp]
    return rows


def event_to_dict(event: MarketEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "name": event.name,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat(),
        "asset_performance": event.asset_performance,
        "macro_conditions": event.macro_conditions,
        "valuation_state": event.valuation_state,
        "credit_conditions": event.credit_conditions,
        "liquidity_state": event.liquidity_state,
        "gold_behaviour": event.gold_behaviour,
        "silver_behaviour": event.silver_behaviour,
    }


def coverage_summary(points_by_code: Mapping[str, Sequence[HistoricalPoint]]) -> dict[str, dict[str, Any]]:
    summary = {}
    for code, points in points_by_code.items():
        ordered = sorted(points, key=lambda item: item.timestamp)
        if not ordered:
            summary[code] = {"rows": 0, "start": None, "end": None}
            continue
        summary[code] = {
            "rows": len(ordered),
            "start": ordered[0].timestamp.date().isoformat(),
            "end": ordered[-1].timestamp.date().isoformat(),
        }
    return summary


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_multpl_date(value: str) -> datetime | None:
    for fmt in ("%b %d %Y", "%B %d %Y", "%b %Y", "%B %Y"):
        try:
            return datetime.strptime(value.replace(",", ""), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_unix_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned == ".":
        return None
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        parsed = float(match.group(0))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def clean_html(value: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"&[#A-Za-z0-9]+;", " ", text)
    return " ".join(text.split())


def stablecoin_value(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in ("peggedUSD", "usd", "value"):
            parsed = stablecoin_value(value.get(key))
            if parsed is not None:
                return parsed
        return None
    return parse_float(value)


def month_start(timestamp: datetime) -> datetime:
    return datetime(timestamp.year, timestamp.month, 1, tzinfo=timezone.utc)


def prior_value(history: Sequence[tuple[datetime, float]], timestamp: datetime, *, months: int) -> float | None:
    target_year = timestamp.year
    target_month = timestamp.month - months
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    target = datetime(target_year, target_month, 1, tzinfo=timezone.utc)
    candidates = [value for candidate_timestamp, value in history if candidate_timestamp <= target]
    return candidates[-1] if candidates else None


def normalize(value: float | None, *, low: float, high: float, default: float) -> float:
    if value is None or high <= low:
        return default
    return clamp((float(value) - low) / (high - low) * 100.0, 0.0, 100.0)


def credit_stress_from_values(values: Mapping[str, float]) -> float:
    baa = values.get("FRED_BAA")
    aaa = values.get("FRED_AAA")
    spread = max(0.0, baa - aaa) if baa is not None and aaa is not None else None
    high_yield = values.get("FRED_BAMLH0A0HYM2")
    curve = values.get("FRED_T10Y2Y")
    components = [
        normalize(spread, low=0.5, high=3.0, default=50.0),
        normalize(high_yield, low=2.0, high=10.0, default=50.0),
        normalize(-(curve or 0.0), low=-1.0, high=2.0, default=50.0),
    ]
    return sum(components) / len(components)


def liquidity_from_values(values: Mapping[str, float]) -> float:
    fed_balance = values.get("FED_BALANCE_SHEET")
    reverse_repo = values.get("REVERSE_REPO")
    if fed_balance is None and reverse_repo is None:
        return 50.0
    fed_component = normalize(fed_balance, low=500_000.0, high=10_000_000.0, default=50.0)
    rrp_drag = normalize(reverse_repo, low=0.0, high=2_500_000.0, default=20.0)
    return clamp(fed_component * 0.75 + (100.0 - rrp_drag) * 0.25, 0.0, 100.0)


def trailing_return(current: float | None, previous: float | None) -> float:
    if current is None or previous is None or previous <= 0.0:
        return 0.0
    return (current - previous) / previous


def confidence_from_completeness(values: Mapping[str, float]) -> float:
    expected = ("SP500", "SHILLER_CAPE", "FRED_BAA", "FRED_AAA", "FRED_CPIAUCSL", "FRED_T10Y2Y")
    present = sum(1 for key in expected if values.get(key) is not None)
    return round(clamp(35.0 + present / len(expected) * 55.0, 0.0, 90.0), 6)


def pct_change(current: float, previous: float | None) -> float:
    if previous is None or previous <= 0.0:
        return 0.0
    return round((current - previous) / previous * 100.0, 6)


def coverage_report_from_points(
    specs: Sequence[DatasetSpec],
    points_by_code: Mapping[str, Sequence[HistoricalPoint]],
    *,
    current_year: int | None = None,
) -> list[dict[str, Any]]:
    end_year = current_year or datetime.now(timezone.utc).year
    report = []
    for spec in specs:
        ordered = sorted(points_by_code.get(spec.target_code, ()), key=lambda item: item.timestamp)
        observed_start = ordered[0].timestamp.year if ordered else None
        observed_end = ordered[-1].timestamp.year if ordered else None
        expected_start = max(1900, spec.start_year)
        expected_months = max(1, (end_year - expected_start + 1) * 12)
        observed_months = distinct_month_count(ordered)
        missing_pct = round(clamp(1.0 - observed_months / expected_months, 0.0, 1.0) * 100.0, 2)
        row = {
            "dataset": spec.name,
            "category": spec.category,
            "provider": spec.provider,
            "source": spec.source,
            "expected_start_year": expected_start,
            "observed_start_year": observed_start,
            "observed_end_year": observed_end,
            "latest_year": end_year,
            "target_table": spec.table_name,
            "target_code": spec.target_code,
            "observed_months": observed_months,
            "expected_months": expected_months,
            "missing_data_percentage": missing_pct,
            "automatic_backfill": spec.automatic_backfill,
            "license_note": spec.license_note,
        }
        row["coverage_status"] = coverage_status(missing_pct, observed_start)
        report.append(row)
    return report


def build_validation_dataset(
    points_by_code: Mapping[str, Sequence[HistoricalPoint]],
    forecasts: Sequence[ReconstructedForecast],
    *,
    horizon_months: int = 12,
) -> list[HistoricalValidationRow]:
    sp500 = monthly_price_map(points_by_code.get("SP500", ()))
    grouped = forecasts_by_month(forecasts)
    rows: list[HistoricalValidationRow] = []
    for timestamp, month_forecasts in sorted(grouped.items()):
        current_price = sp500.get(timestamp)
        future_timestamp = add_months(timestamp, horizon_months)
        future_price = value_at_or_after(sp500, future_timestamp)
        if current_price is None or future_price is None or current_price <= 0.0:
            continue
        realized_return = (future_price - current_price) / current_price
        realized_outcome = 1 if realized_return <= -0.20 else 0
        panic_probability = month_forecasts.get("panic_probability_12m", 0.5)
        prediction_error = abs(panic_probability - realized_outcome)
        rows.append(
            HistoricalValidationRow(
                forecast_date=timestamp,
                horizon_months=horizon_months,
                inputs=reconstructed_inputs(month_forecasts),
                predictions=dict(month_forecasts),
                realized_outcome=realized_outcome,
                realized_return=round(realized_return, 10),
                prediction_error=round(prediction_error, 10),
                lead_time_months=lead_time_to_threshold(sp500, timestamp, horizon_months, threshold_return=-0.20),
            )
        )
    return rows


def build_research_report(
    specs: Sequence[DatasetSpec],
    events: Sequence[MarketEvent],
    points_by_code: Mapping[str, Sequence[HistoricalPoint]],
    validation_rows: Sequence[HistoricalValidationRow],
    *,
    as_of: datetime | None = None,
) -> HistoricalResearchReport:
    generated_at = as_of or datetime.now(timezone.utc)
    coverage = coverage_report_from_points(specs, points_by_code, current_year=generated_at.year)
    missing = mean_or_zero([row["missing_data_percentage"] for row in coverage])
    backfill_completeness = round(clamp(100.0 - missing, 0.0, 100.0), 6)
    event_coverage = historical_event_coverage(events, points_by_code)
    validation_readiness = validation_readiness_score(validation_rows)
    maturity = forecast_maturity_estimate(validation_rows)
    research_completeness = round(
        clamp(
            backfill_completeness * 0.35
            + event_coverage * 0.20
            + validation_readiness * 0.25
            + maturity * 0.20,
            0.0,
            100.0,
        ),
        6,
    )
    return HistoricalResearchReport(
        generated_at=generated_at,
        coverage_by_dataset=coverage,
        missing_data_percentage=round(missing, 6),
        backfill_completeness=backfill_completeness,
        historical_event_coverage=event_coverage,
        validation_readiness=validation_readiness,
        forecast_maturity_estimate=maturity,
        research_completeness_estimate=research_completeness,
        remaining_historical_gaps=remaining_historical_gaps(coverage),
        self_learning_process=monthly_self_learning_process(),
    )


def historical_event_coverage(
    events: Sequence[MarketEvent],
    points_by_code: Mapping[str, Sequence[HistoricalPoint]],
) -> float:
    if not events:
        return 0.0
    monthly_codes = {code: set(month_start(point.timestamp) for point in points) for code, points in points_by_code.items()}
    required_codes = ("SP500", "SHILLER_CAPE", "FRED_BAA", "FRED_AAA", "GOLD", "SILVER")
    scores = []
    for event in events:
        event_month = datetime(event.start_date.year, event.start_date.month, 1, tzinfo=timezone.utc)
        present = sum(1 for code in required_codes if event_month in monthly_codes.get(code, set()))
        scores.append(present / len(required_codes) * 100.0)
    return round(mean_or_zero(scores), 6)


def validation_readiness_score(rows: Sequence[HistoricalValidationRow]) -> float:
    if not rows:
        return 0.0
    span_months = months_between(rows[0].forecast_date, rows[-1].forecast_date) + 1
    depth = min(len(rows) / 120.0, 1.0) * 45.0
    span = min(span_months / 360.0, 1.0) * 35.0
    quality = (1.0 - clamp(mean_or_zero([row.prediction_error for row in rows]), 0.0, 1.0)) * 20.0
    return round(clamp(depth + span + quality, 0.0, 100.0), 6)


def forecast_maturity_estimate(rows: Sequence[HistoricalValidationRow]) -> float:
    if not rows:
        return 0.0
    event_positive_count = sum(1 for row in rows if row.realized_outcome == 1)
    sample_component = min(len(rows) / 240.0, 1.0) * 55.0
    event_component = min(event_positive_count / 8.0, 1.0) * 30.0
    lead_component = min(mean_or_zero([row.lead_time_months for row in rows]) / 12.0, 1.0) * 15.0
    return round(clamp(sample_component + event_component + lead_component, 0.0, 100.0), 6)


def remaining_historical_gaps(coverage: Sequence[Mapping[str, Any]]) -> list[str]:
    gaps = []
    for row in coverage:
        missing = float(row["missing_data_percentage"])
        if missing >= 75.0:
            gaps.append(f"{row['dataset']}: sparse coverage for {row['category']}")
        elif row.get("observed_start_year") is None:
            gaps.append(f"{row['dataset']}: no observations loaded")
        elif int(row["observed_start_year"]) > int(row["expected_start_year"]):
            gaps.append(f"{row['dataset']}: starts {row['observed_start_year']}, expected {row['expected_start_year']}")
    return gaps


def monthly_self_learning_process() -> dict[str, str]:
    return {
        "trigger": "Run after the existing monthly reporting cycle completes.",
        "append": "Persist current model inputs and predictions to forecast_history metadata using the existing pipeline output.",
        "resolve": "When the forecast horizon matures, attach realized outcome, realized return, prediction error, and lead time in a validation metadata row.",
        "audit": "Recompute forecast_outcomes rolling validation metrics from forecast_history without changing production weights.",
        "governance": "Surface recommended-only weight changes through existing audit/reporting tables for human review.",
    }


def research_report_to_dict(report: HistoricalResearchReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "coverage_by_dataset": report.coverage_by_dataset,
        "missing_data_percentage": report.missing_data_percentage,
        "backfill_completeness": report.backfill_completeness,
        "historical_event_coverage": report.historical_event_coverage,
        "validation_readiness": report.validation_readiness,
        "forecast_maturity_estimate": report.forecast_maturity_estimate,
        "research_completeness_estimate": report.research_completeness_estimate,
        "remaining_historical_gaps": report.remaining_historical_gaps,
        "self_learning_process": report.self_learning_process,
    }


def validation_row_to_dict(row: HistoricalValidationRow) -> dict[str, Any]:
    return {
        "forecast_date": row.forecast_date.isoformat(),
        "horizon_months": row.horizon_months,
        "inputs": row.inputs,
        "predictions": row.predictions,
        "realized_outcome": row.realized_outcome,
        "realized_return": row.realized_return,
        "prediction_error": row.prediction_error,
        "lead_time_months": row.lead_time_months,
    }


def severity_for_report(report: HistoricalResearchReport) -> str:
    if report.research_completeness_estimate < 40.0:
        return "HIGH"
    if report.research_completeness_estimate < 70.0:
        return "MEDIUM"
    return "LOW"


def confidence_from_validation_row(row: HistoricalValidationRow) -> float:
    return round(clamp((1.0 - row.prediction_error) * 100.0, 0.0, 100.0), 6)


def forecasts_by_month(forecasts: Sequence[ReconstructedForecast]) -> dict[datetime, dict[str, float]]:
    grouped: dict[datetime, dict[str, float]] = {}
    for forecast in forecasts:
        grouped.setdefault(month_start(forecast.forecast_date), {})[forecast.forecast_type] = forecast.forecast_value
    return grouped


def reconstructed_inputs(predictions: Mapping[str, float]) -> dict[str, float]:
    return {
        "panic_probability": predictions.get("panic_probability_12m", 0.5),
        "recovery_probability": predictions.get("recovery_probability_12m", 50.0),
        "buy_score": predictions.get("buy_score", 50.0),
        "sell_score": predictions.get("sell_score", 50.0),
        "expected_return": predictions.get("expected_return_12m", 0.0),
        "expected_drawdown": predictions.get("expected_drawdown_12m", 0.25),
    }


def monthly_price_map(points: Sequence[HistoricalPoint]) -> dict[datetime, float]:
    prices = {}
    for point in sorted(points, key=lambda item: item.timestamp):
        prices[month_start(point.timestamp)] = point.value
    return prices


def value_at_or_after(values: Mapping[datetime, float], timestamp: datetime) -> float | None:
    for candidate in sorted(values):
        if candidate >= timestamp:
            return values[candidate]
    return None


def lead_time_to_threshold(
    values: Mapping[datetime, float],
    timestamp: datetime,
    horizon_months: int,
    *,
    threshold_return: float,
) -> float:
    start = values.get(timestamp)
    if start is None or start <= 0.0:
        return 0.0
    end = add_months(timestamp, horizon_months)
    for candidate in sorted(values):
        if candidate <= timestamp or candidate > end:
            continue
        realized = (values[candidate] - start) / start
        if realized <= threshold_return:
            return float(months_between(timestamp, candidate))
    return 0.0


def add_months(timestamp: datetime, months: int) -> datetime:
    year = timestamp.year
    month = timestamp.month + months
    while month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def months_between(start: datetime, end: datetime) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def distinct_month_count(points: Sequence[HistoricalPoint]) -> int:
    return len({(point.timestamp.year, point.timestamp.month) for point in points})


def coverage_status(missing_pct: float, observed_start: int | None) -> str:
    if observed_start is None:
        return "MISSING"
    if missing_pct >= 75.0:
        return "SPARSE"
    if missing_pct >= 35.0:
        return "PARTIAL"
    return "GOOD"


def mean_or_zero(values: Sequence[float]) -> float:
    clean = [float(value) for value in values]
    return mean(clean) if clean else 0.0
