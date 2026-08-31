import pytest
import asyncio
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from Breakout_Radar import AsyncExchange

@pytest.mark.asyncio
async def test_async_exchange_analyze_symbol():
    exchange = AsyncExchange()

    # Mock feed.fetch_historical_klines
    mock_df = pd.DataFrame({
        'open': [100.0] * 50,
        'high': [105.0] * 50,
        'low': [99.0] * 50,
        'close': [104.0] * 50,
        'volume': [1000.0] * 50
    })
    exchange.feed.fetch_historical_klines = AsyncMock(return_value=mock_df)

    # Mock engine.evaluate_symbol
    exchange.engine.evaluate_symbol = MagicMock(return_value={
        'symbol': 'BTCUSDT',
        'score': 85.0,
        'direction': 'LONG',
        'flags': ['COILED', 'VOL_SPIKE']
    })

    sem = asyncio.Semaphore(5)
    result = await exchange.analyze_symbol('BTCUSDT', sem)

    assert result is not None
    assert result['symbol'] == 'BTCUSDT'
    assert result['score'] == 85.0
    assert 'COILED' in result['details']
    assert 'VOL_SPIKE' in result['details']

@pytest.mark.asyncio
async def test_async_exchange_low_score_filtered():
    exchange = AsyncExchange()
    mock_df = pd.DataFrame({
        'open': [100.0] * 50,
        'high': [101.0] * 50,
        'low': [99.0] * 50,
        'close': [100.0] * 50,
        'volume': [100.0] * 50
    })
    exchange.feed.fetch_historical_klines = AsyncMock(return_value=mock_df)
    exchange.engine.evaluate_symbol = MagicMock(return_value={
        'symbol': 'BTCUSDT',
        'score': 10.0,
        'direction': 'NEUTRAL',
        'flags': []
    })

    sem = asyncio.Semaphore(5)
    result = await exchange.analyze_symbol('BTCUSDT', sem)

    assert result is None
