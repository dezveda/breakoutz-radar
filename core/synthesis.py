"""Synthesis-mode fusion: combines per-exchange candidates into one
cross-exchange confluence signal per symbol.

Design rationale (see conversation): a plain max() across exchanges is
rejected on purpose — it is vulnerable to a single-exchange artifact
(thin book, stale ticker, momentary liquidity gap) producing a false
SNIPER signal that no other venue confirms. A volume-weighted average
dampens single-venue noise, and a confirmation bonus rewards the case
that actually matters for precision: the same breakout appearing on
multiple independent venues at once, which is a materially stronger
signal than any single exchange's score.
"""
from typing import Dict, List
from config import RadarConfig


def fuse_exchange_results(per_exchange: Dict[str, List[dict]], cfg: RadarConfig) -> List[dict]:
    # Group candidate rows by symbol, keeping only same-direction rows together.
    # symbol -> direction -> list of (exchange_name, row)
    grouped: Dict[str, Dict[str, List[tuple]]] = {}
    for exchange_name, rows in per_exchange.items():
        for row in rows:
            symbol = row["symbol"]
            direction = row["direction"]
            grouped.setdefault(symbol, {}).setdefault(direction, []).append((exchange_name, row))

    fused: List[dict] = []
    for symbol, by_direction in grouped.items():
        # If the symbol has conflicting directions across exchanges, keep
        # only the strongest single-exchange read per direction rather than
        # averaging contradictory signals into a meaningless blend.
        best_direction, best_rows = max(by_direction.items(), key=lambda kv: max(r["score"] for _, r in kv[1]))

        exchanges = [name for name, _ in best_rows]
        scores = [r["score"] for _, r in best_rows]
        volumes = [max(r.get("volume", 0.0), 1e-9) for _, r in best_rows]
        total_vol = sum(volumes)

        weighted_score = sum(s * v for s, v in zip(scores, volumes)) / total_vol
        confirmations = len(best_rows)
        bonus = min(cfg.SYNTHESIS_CONFIRMATION_BONUS * (confirmations - 1), cfg.SYNTHESIS_MAX_BONUS)
        final_score = min(100, round(weighted_score + bonus))

        merged_flags = sorted({flag for _, r in best_rows for flag in r.get("flags", [])})
        if confirmations >= 2:
            merged_flags.append("CROSS_CONFIRMED")

        weighted_delta_oi = sum(r.get("delta_oi", 0.0) * v for (_, r), v in zip(best_rows, volumes)) / total_vol
        weighted_z = sum(r.get("z_score", 0.0) * v for (_, r), v in zip(best_rows, volumes)) / total_vol
        weighted_bbw = sum(r.get("bbw", 0.0) * v for (_, r), v in zip(best_rows, volumes)) / total_vol

        fused.append({
            "symbol": symbol,
            "exchanges": exchanges,
            "score": final_score,
            "direction": best_direction,
            "flags": merged_flags,
            "delta_oi": weighted_delta_oi,
            "z_score": weighted_z,
            "bbw": weighted_bbw,
        })

    fused.sort(key=lambda r: r["score"], reverse=True)
    return [r for r in fused if r["score"] >= cfg.DISPLAY_MIN_SCORE]
