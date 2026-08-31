# Breakout Radar (Smart Money Edition)

**Breakout Radar** (also branded as **VECTOR /// RADAR**) is a real-time, high-performance cryptocurrency futures scanner and tactical desktop interface built with Python, PyQt6, `asyncio`, and `aiohttp`.

It monitors Binance USD-M Futures markets to detect early phase transitions—identifying volatility compressions, statistical volume anomalies (Z-Score), micro-structure momentum shifts, and trend alignments before major breakouts occur.

---

## ⚡ Key Features

* **Asynchronous Market Ingestion**: Uses `aiohttp` and `asyncio` to scan Binance USD-M Futures (USDT pairs only, top 40 candidates pre-filtered by volume and volatility) with rate-limit tracking (`X-MBX-USED-WEIGHT-1M`) and auto-cooldown protection.
* **Statistical Volume Anomaly (Z-Score)**: Measures volume spikes as a statistical Z-Score against the 48-period 1h volume mean ($Z > 1.5$ and $Z > 3.0$) while filtering out stale volume ("zombie" assets with $< 10\%$ volume in the last 4 hours).
* **Volatility Compression Squeeze (`COILED`)**: Detects low-volatility compression states using normalized Bollinger Band Width (BBW $< 0.03$), highlighting potential explosive moves.
* **Micro-Structure Analysis (15m & 1H)**: Analyzes the current live forming 15-minute power candle for real-time momentum ($>70\%$ body ratio and $>0.5\%$ price move) or rejection penalties ($-30$ points if upper wick $> 60\%$), alongside 1-hour macro trend alignments (SMA 7 vs. SMA 25).
* **Open Interest (OI) Check**: Confirms active open interest ($OI > 0$) on Binance Futures for top candidates scoring above 30 points.
* **Tactical Frameless GUI**:
  * Dark cyber-themed UI designed with PyQt6.
  * Live API weight monitor bar.
  * Countdown timer for scan cycles (45-second default refresh rate).
  * Color-coded scoring system and signal flag tags.
  * Draggable title bar and native smooth window resizing.

---

## 📊 Signal & Scoring System

The system evaluates assets on a 0–95 probability score (capped at 100, displaying candidates with score $> 25$):

| Score | Status | Description |
| :--- | :--- | :--- |
| **> 80** | **SNIPER ENTRY** | High-conviction breakout candidate with combined volume spike, compression, and momentum. |
| **> 60** | **WATCHLIST** | Emerging setup showing potential momentum or volatility compression. |
| **< 60** | **NO TRADE** | Low signal quality or trend misalignment (display threshold $> 25$). |

### Scoring Breakdown

| Factor | Condition | Score Impact |
| :--- | :--- | :--- |
| **Volume Anomaly** | Statistical Z-Score $Z > 3.0$ ($Z > 1.5$ grants +10) | +25 pts |
| **Squeeze Compression** | Bollinger Band Width $\text{BBW} < 0.03$ (`COILED`) | +20 pts |
| **Live Momentum** | Current 15m candle body ratio $> 70\%$ & price move $> 0.5\%$ | +15 pts |
| **Macro Trend** | 1h SMA 7 > SMA 25 alignment | +15 pts |
| **48h High Proximity** | Price within 1% of 48-hour high (`ATH_NEAR`) | +10 pts |
| **Active Open Interest** | Futures $OI > 0$ (evaluated if score $> 30$) | +10 pts |
| **Candle Rejection Penalty** | Current 15m upper wick $> 60\%$ of total candle height | -30 pts |
| **Counter-Trend Penalty** | 24h change $> +5.0\%$ when SMA 7 $\le$ SMA 25 | -10 pts |

### Signal Badges & Flags

* `COILED`: Extreme volatility compression (Bollinger Band Squeeze).
* `VOL_SPIKE`: Statistical volume anomaly ($Z\text{-Score} > 3.0$).
* `MOMENTUM`: 15-minute live power candle formation ($>70\%$ body ratio, $>0.5\%$ move).
* `ATH_NEAR`: Asset is trading within 1% of its 48-hour high.

---

## 🛠️ Tech Stack & Requirements

* **Language**: Python 3.9+
* **GUI Framework**: PyQt6
* **Data & Analytics**: NumPy, Pandas
* **Networking**: Aiohttp, Asyncio

### Dependencies

Install required Python packages:

```bash
pip install pyqt6 aiohttp pandas numpy
```

---

## 🚀 Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/dezveda/breakoutz-radar.git
   cd breakoutz-radar
   ```

2. **Run the application**:
   ```bash
   python Breakout_Radar.py
   ```

---

## ⚙️ Configuration Options

You can adjust scan parameters in `Breakout_Radar.py` under the `CONF` dictionary:

```python
CONF = {
    'MIN_VOL_24H': 15_000_000,   # Minimum 24h volume filter ($15M USD)
    'BLACKLIST': ['USDCUSDT', 'BUSDUSDT', 'TUSDUSDT', 'USDPUSDT', 'FDUSDUSDT'], # Stablecoins blacklist
    'REFRESH_RATE': 45,          # Scan cycle interval in seconds
    'MAX_CONCURRENT_REQ': 8,     # Max concurrent HTTP requests
    'API_WEIGHT_LIMIT': 1100     # Binance API weight threshold (Limit: 1200)
}
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
