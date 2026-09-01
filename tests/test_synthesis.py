from config import RadarConfig
from core.synthesis import fuse_exchange_results


def test_single_exchange_passthrough():
    cfg = RadarConfig()
    per_exchange = {
        "BINANCE": [{"symbol": "BTCUSDT", "score": 60, "direction": "LONG",
                      "flags": ["VOL_SPIKE"], "volume": 1000.0, "delta_oi": 3.0,
                      "z_score": 2.0, "bbw": 0.02}],
    }
    fused = fuse_exchange_results(per_exchange, cfg)
    assert len(fused) == 1
    assert fused[0]["score"] == 60
    assert fused[0]["exchanges"] == ["BINANCE"]
    assert "CROSS_CONFIRMED" not in fused[0]["flags"]


def test_cross_confirmation_adds_bonus_not_max():
    cfg = RadarConfig()
    per_exchange = {
        "BINANCE": [{"symbol": "ETHUSDT", "score": 50, "direction": "LONG",
                      "flags": [], "volume": 1000.0, "delta_oi": 1.0, "z_score": 1.5, "bbw": 0.02}],
        "BYBIT": [{"symbol": "ETHUSDT", "score": 60, "direction": "LONG",
                    "flags": [], "volume": 1000.0, "delta_oi": 1.5, "z_score": 1.8, "bbw": 0.02}],
    }
    fused = fuse_exchange_results(per_exchange, cfg)
    row = fused[0]
    # Equal-volume average of 50/60 is 55; +bonus (15 for one extra confirmation) = 70.
    # Must be strictly less than a naive max() of 60+bonus, proving this isn't max-based.
    assert row["score"] == 70
    assert "CROSS_CONFIRMED" in row["flags"]
    assert set(row["exchanges"]) == {"BINANCE", "BYBIT"}


def test_conflicting_direction_keeps_strongest_not_averaged():
    cfg = RadarConfig()
    per_exchange = {
        "BINANCE": [{"symbol": "SOLUSDT", "score": 80, "direction": "LONG",
                      "flags": [], "volume": 1000.0, "delta_oi": 2.0, "z_score": 3.0, "bbw": 0.01}],
        "OKX": [{"symbol": "SOLUSDT", "score": 40, "direction": "SHORT",
                  "flags": [], "volume": 1000.0, "delta_oi": -2.0, "z_score": 1.0, "bbw": 0.02}],
    }
    fused = fuse_exchange_results(per_exchange, cfg)
    row = fused[0]
    assert row["direction"] == "LONG"
    assert row["score"] == 80  # single confirming exchange for the winning direction, no averaging-in of the conflict
    assert row["exchanges"] == ["BINANCE"]
