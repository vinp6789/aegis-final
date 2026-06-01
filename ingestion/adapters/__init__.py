"""Free-source ingestion adapters for Phase 3."""

from ingestion.adapters.base_client import BaseIngestionClient, FetchResult, SourceHealthMetrics
from ingestion.adapters.alternative_me_client import AlternativeMeFearGreedClient
from ingestion.adapters.amfi_client import AMFIClient
from ingestion.adapters.binance_expanded_client import BinanceExpandedClient
from ingestion.adapters.bis_client import BISClient
from ingestion.adapters.coinbase_client import CoinbaseClient
from ingestion.adapters.coingecko_expanded_client import CoinGeckoExpandedClient
from ingestion.adapters.defillama_stablecoin_client import DefiLlamaStablecoinClient
from ingestion.adapters.exchange_flow_client import ExchangeFlowClient
from ingestion.adapters.fred_client import FREDClient
from ingestion.adapters.government_capex_client import GovernmentCapexClient
from ingestion.adapters.gst_collections_client import GSTCollectionsClient
from ingestion.adapters.nse_client import NSEClient
from ingestion.adapters.oecd_client import OECDClient
from ingestion.adapters.pmi_client import PMIClient
from ingestion.adapters.rbi_liquidity_client import RBILiquidityClient
from ingestion.adapters.us_treasury_client import USTreasuryClient
from ingestion.adapters.world_bank_client import WorldBankClient
from ingestion.adapters.yfinance_client import YFinanceClient

__all__ = [
    "AlternativeMeFearGreedClient",
    "AMFIClient",
    "BaseIngestionClient",
    "BinanceExpandedClient",
    "BISClient",
    "CoinbaseClient",
    "CoinGeckoExpandedClient",
    "DefiLlamaStablecoinClient",
    "ExchangeFlowClient",
    "FetchResult",
    "FREDClient",
    "GovernmentCapexClient",
    "GSTCollectionsClient",
    "NSEClient",
    "OECDClient",
    "PMIClient",
    "RBILiquidityClient",
    "SourceHealthMetrics",
    "USTreasuryClient",
    "WorldBankClient",
    "YFinanceClient",
]
