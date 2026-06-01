-- Deployment seed for asset_registry.
-- Required before /run/data-collection writes daily_market_metrics rows.
-- Idempotent: updates metadata for existing asset ids and does not duplicate rows.

INSERT INTO asset_registry (
    asset_id,
    asset_name,
    asset_class,
    region,
    data_provider,
    is_active
)
VALUES
    ('NIFTY 50', 'NIFTY 50 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY NEXT 50', 'NIFTY Next 50 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY 100', 'NIFTY 100 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY 200', 'NIFTY 200 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY 500', 'NIFTY 500 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY MIDCAP 50', 'NIFTY Midcap 50 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY MIDCAP 100', 'NIFTY Midcap 100 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY SMALLCAP 100', 'NIFTY Smallcap 100 Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY BANK', 'NIFTY Bank Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY AUTO', 'NIFTY Auto Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY IT', 'NIFTY IT Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY PHARMA', 'NIFTY Pharma Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY FMCG', 'NIFTY FMCG Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY METAL', 'NIFTY Metal Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY REALTY', 'NIFTY Realty Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY ENERGY', 'NIFTY Energy Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NIFTY INFRA', 'NIFTY Infrastructure Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE),
    ('NSE_INDEX', 'Generic NSE Index', 'EQUITY_INDEX', 'INDIA', 'NSE', TRUE)
ON CONFLICT (asset_id) DO UPDATE
SET
    asset_name = EXCLUDED.asset_name,
    asset_class = EXCLUDED.asset_class,
    region = EXCLUDED.region,
    data_provider = EXCLUDED.data_provider,
    is_active = EXCLUDED.is_active;
