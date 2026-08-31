# Breakoutz Radar 🚀

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

**Breakoutz Radar** is a real-time market scanner, volatility monitoring, and breakout detection engine for cryptocurrencies and financial markets. It continuously tracks live price feeds, volume spikes, and technical indicator setups to detect high-probability breakout momentum before major price swings occur.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#-usage)
  - [Running the Scanner](#running-the-scanner)
  - [CLI Commands](#cli-commands)
- [Configuration](#-configuration)
- [Supported Exchanges \& Data Feeds](#-supported-exchanges--data-feeds)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ✨ Features

- **Real-time Breakout Detection:** Scans hundreds of market pairs simultaneously for consolidation squeezes, range breaches, and momentum breakouts.
- **Volume & Volatility Alerts:** Detects sudden abnormal volume bursts and volatility expansion (e.g., Bollinger Band squeeze releases).
- **Multi-Exchange Websocket Support:** Real-time data streaming via WebSockets with automatic reconnection handling.
- **Custom Alert Engine:** Deliver instant notifications via Telegram, Discord, Webhooks, or desktop popups.
- **Flexible Technical Indicators:** Built-in technical analysis using RSI, MACD, Volume Profile, ATR, and Moving Averages.
- **Configurable Risk Management:** Filter signals based on market cap, liquidity, trend strength, and risk parameters.

---

## 🏗 Architecture

```
                       ┌─────────────────────────┐
                       │   Market Data Streams   │
                       │  (Binance, Bybit, etc)  │
                       └────────────┬────────────┘
                                    │ WebSocket / REST
                                    ▼
                       ┌─────────────────────────┐
                       │   Data Ingestion &      │
                       │  Normalization Engine   │
                       └────────────┬────────────┘
                                    │ Normalized Tickers / Candles
                                    ▼
                       ┌─────────────────────────┐
                       │ Breakout Analysis Engine│
                       │ (Vol, Squeeze, Pattern) │
                       └────────────┬────────────┘
                                    │ Signals & Alerts
                                    ▼
           ┌────────────────────────┴────────────────────────┐
           │                                                 │
           ▼                                                 ▼
┌────────────────────┐                            ┌────────────────────┐
│ Notification Bus   │                            │  Dashboard / CLI   │
│ (Telegram/Discord) │                            │      Display       │
└────────────────────┘                            └────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.9+** or **Node.js 18+** (depending on deployment target)
- **Git**

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dezveda/breakoutz-radar.git
   cd breakoutz-radar
   ```

2. **Create and activate a virtual environment (Python):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Copy the example environment configuration:**
   ```bash
   cp .env.example .env
   ```

---

## 💡 Usage

### Running the Scanner

Start the breakout radar scanner with default settings:

```bash
python -m breakoutz_radar.main --config config.json
```

To run with live Telegram alerts enabled:

```bash
python -m breakoutz_radar.main --alerts telegram --verbose
```

### CLI Commands

| Command | Description |
| :--- | :--- |
| `breakoutz scan` | Run a single pass scan across specified market pairs. |
| `breakoutz watch` | Launch the continuous live websocket radar scanner. |
| `breakoutz test-alerts` | Send test messages to configured notification channels. |

---

## ⚙️ Configuration

Customize scanner sensitivity, pair filters, and notification settings in `config.json` or `.env`:

```json
{
  "scanner": {
    "timeframe": "15m",
    "min_volume_24h": 1000000,
    "squeeze_threshold": 0.02,
    "volume_spike_multiplier": 2.5
  },
  "notifications": {
    "telegram": {
      "enabled": true,
      "bot_token": "YOUR_BOT_TOKEN",
      "chat_id": "YOUR_CHAT_ID"
    }
  }
}
```

---

## 📊 Supported Exchanges & Data Feeds

- [x] Binance (Spot & USDT Futures)
- [x] Bybit (Linear Futures)
- [x] OKX
- [x] KuCoin
- [ ] Coinbase Advanced Trade (In Progress)

---

## 🗺 Roadmap

- [ ] Interactive Web Dashboard (React / Tailwind)
- [ ] Automated Order Execution / Webhook Trading integration
- [ ] Machine Learning signal confidence scoring
- [ ] Multi-timeframe confluence filters

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📜 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

---

## ⚠️ Disclaimer

*This software is for educational and research purposes only. Do not use it as financial advice. Trading cryptocurrencies and financial instruments involves significant risk of loss. Always manage your risk responsibly.*
