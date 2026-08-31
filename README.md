# Breakout Radar (Smart Money Edition)

**Breakout Radar** (also branded as **VECTOR /// RADAR**) is a real-time, high-performance cryptocurrency futures scanner and tactical desktop interface built with Python, PyQt6, `asyncio`, and `aiohttp`.

It monitors Binance USD-M Futures markets to detect early phase transitions—identifying volatility compressions, statistical volume anomalies (Z-Score), micro-structure momentum shifts, and trend alignments before major breakouts occur.

---

## ⚡ Key Features

* **Asynchronous Market Ingestion**: Uses `aiohttp` and `asyncio` to scan Binance USD-M Futures with rate-limit tracking (`X-MBX-USED-WEIGHT-1M`) and auto-cooldown protection.
* **Statistical Volume Anomaly (Z-Score)**: Measures volume spikes relative to historical moving averages ($Z > 1.5$ and $Z > 3.0$) while filtering out stale volume ("zombie" assets).
* **Volatility Compression Squeeze (`COILED`)**: Detects low-volatility compression states using normalized Bollinger Band Width (BBW $< 0.03$), highlighting potential explosive moves.
* **Micro-Structure Analysis (15m & 1H)**: Analyzes 15-minute power candles (body-to-wick ratios) and 1-hour macro trend alignments (SMA 7 vs. SMA 25).
* **Open Interest (OI) Verification**: Validates futures contract liquidity and active open interest for top breakout candidates.
* **Tactical Frameless GUI**:
  * Dark cyber-themed UI designed with PyQt6.
  * Live API weight monitor bar.
  * Countdown timer for scan cycles (45-second default refresh rate).
  * Color-coded scoring system and signal flag tags.
  * Draggable title bar and native smooth window resizing.

---

## 📊 Signal & Scoring System

The system evaluates assets on a 0–100 probability score:

| Score | Status | Description |
| :--- | :--- | :--- |
| **> 80** | **SNIPER ENTRY** | High-conviction breakout candidate with combined volume spike, compression, and momentum. |
| **> 60** | **WATCHLIST** | Emerging setup showing potential momentum or volatility compression. |
| **< 60** | **NO TRADE** | Low signal quality or trend misalignment. |

### Signal Badges & Flags

* `COILED`: Extreme volatility compression (Bollinger Band Squeeze).
* `VOL_SPIKE`: Statistical volume anomaly ($Z\text{-Score} > 3.0$).
* `MOMENTUM`: 15-minute power candle formation ($>70\%$ body ratio).
* `ATH_NEAR`: Asset is trading near recent highs or All-Time Highs (top 1%).

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
   git clone https://github.com/your-username/breakout-radar.git
   cd breakout-radar
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
