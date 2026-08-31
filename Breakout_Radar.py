import sys
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                             QHeaderView, QProgressBar, QFrame, QPushButton, QSizeGrip)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QPoint, QRect, QSize
from PyQt6.QtGui import QColor, QFont, QCursor, QMouseEvent, QAction

import config
from core.scanner import MarketScanner

# ==============================================================================
# DATA ENGINE AND SCANNER THREAD
# ==============================================================================
class AsyncExchange(QThread):
    data_signal = pyqtSignal(list)
    status_signal = pyqtSignal(str)
    weight_signal = pyqtSignal(int)
    timer_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.used_weight = 0

    async def get_ticker_24hr(self, session) -> list:
        try:
            url = f"{config.BASE_URL}/fapi/v1/ticker/24hr"
            async with session.get(url, timeout=8) as resp:
                w = resp.headers.get('X-MBX-USED-WEIGHT-1M')
                if w:
                    self.used_weight = int(w)
                    self.weight_signal.emit(self.used_weight)
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return []

    async def fetch_active_usdt_pairs(self, session) -> list:
        url = f"{config.BASE_URL}/fapi/v1/exchangeInfo"
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [
                        s["symbol"] for s in data.get("symbols", [])
                        if s["contractType"] == "PERPETUAL"
                        and s["quoteAsset"] == "USDT"
                        and s["status"] == "TRADING"
                    ]
        except Exception:
            pass
        return []

    async def run_loop(self):
        async with aiohttp.ClientSession(headers={"User-Agent": "BreakoutRadar/2.0"}) as session:
            scanner = MarketScanner(session)
            while self.running:
                try:
                    self.status_signal.emit("📊 UPDATING BTC BENCHMARK METRICS...")
                    await scanner.update_benchmark_cache()

                    self.status_signal.emit("🔍 FETCHING ACTIVE USDT PAIRS...")
                    symbols = await self.fetch_active_usdt_pairs(session)
                    if not symbols:
                        await asyncio.sleep(5)
                        continue

                    self.status_signal.emit("🔍 GLOBAL SCAN IN PROGRESS...")
                    tickers = await self.get_ticker_24hr(session)
                    ticker_map = {t['symbol']: t for t in tickers if isinstance(t, dict) and 'symbol' in t}

                    # Filter top liquid pairs
                    filtered_symbols = []
                    for s in symbols:
                        t = ticker_map.get(s)
                        if t:
                            try:
                                v = float(t.get('quoteVolume', 0))
                                if v > 10_000_000:
                                    filtered_symbols.append((s, v * abs(float(t.get('priceChangePercent', 0)))))
                            except Exception:
                                continue
                        else:
                            filtered_symbols.append((s, 0))

                    filtered_symbols.sort(key=lambda x: x[1], reverse=True)
                    target_symbols = [s[0] for s in filtered_symbols[:40]] if filtered_symbols else symbols[:40]

                    self.status_signal.emit(f"🔬 QUANT ANALYSIS ON {len(target_symbols)} ASSETS...")

                    sem = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)

                    async def bound_evaluate(s):
                        async with sem:
                            return await scanner.evaluate_symbol(s, ticker_map.get(s, {}))

                    tasks = [bound_evaluate(s) for s in target_symbols]
                    results = []
                    for f in asyncio.as_completed(tasks):
                        res = await f
                        if res is not None and res.get("probability", 0) >= config.DISPLAY_MIN_PROBABILITY:
                            results.append(res)

                    results.sort(key=lambda x: x["probability"], reverse=True)

                    self.data_signal.emit(results)
                    self.status_signal.emit(f"✅ FOUND {len(results)} QUALIFIED OPPORTUNITIES")

                except Exception as e:
                    self.status_signal.emit(f"⚠️ NETWORK ERROR: {str(e)} - RETRYING...")
                    await asyncio.sleep(5)

                # Refresh Countdown
                for i in range(config.SCAN_INTERVAL, 0, -1):
                    if not self.running:
                        break
                    self.timer_signal.emit(f"NEXT SCAN: {i}s")
                    await asyncio.sleep(1)

    def run(self):
        asyncio.run(self.run_loop())

    def stop(self):
        self.running = False


# ==============================================================================
# UI (VISUALIZACIÓN TÁCTICA QUANT - FRAMELESS & RESIZABLE)
# ==============================================================================
class ModernTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 0, 0, 0)
        self.layout.setSpacing(0)

        # Title / Logo area
        self.title_lbl = QLabel("QUANT /// BREAKOUT RADAR")
        self.title_lbl.setStyleSheet("""
            color: #00F0FF;
            font-family: 'Segoe UI';
            font-weight: 900;
            font-size: 12px;
            letter-spacing: 2px;
        """)
        self.layout.addWidget(self.title_lbl)
        self.layout.addStretch()

        # Status Label inside TitleBar
        self.status_lbl = QLabel("SYSTEM READY")
        self.status_lbl.setStyleSheet("color: #666; font-size: 10px; padding-right: 15px;")
        self.layout.addWidget(self.status_lbl)

        # Timer Label
        self.timer_lbl = QLabel("")
        self.timer_lbl.setStyleSheet("color: #00F0FF; font-size: 10px; font-weight: bold; padding-right: 10px;")
        self.layout.insertWidget(2, self.timer_lbl)

        # Window Controls
        btn_style = """
            QPushButton { border: none; background: transparent; color: #888; font-weight: bold; }
            QPushButton:hover { background: #1e2329; color: #fff; }
        """
        close_style = """
            QPushButton { border: none; background: transparent; color: #888; font-weight: bold; }
            QPushButton:hover { background: #ff3333; color: #fff; }
        """

        self.btn_min = QPushButton("—")
        self.btn_min.setFixedSize(40, 30)
        self.btn_min.setStyleSheet(btn_style)
        self.btn_min.clicked.connect(self.parent.showMinimized)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(40, 30)
        self.btn_close.setStyleSheet(close_style)
        self.btn_close.clicked.connect(self.parent.close)

        self.layout.addWidget(self.btn_min)
        self.layout.addWidget(self.btn_close)

        self.start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.parent.move(self.parent.pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class BreakoutRadarWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(800, 850)

        self.grip_size = 10
        self.resizing = False
        self.resize_edge = None
        self.old_pos = None

        self.setStyleSheet("""
            QMainWindow { background-color: #0b0e11; border: 1px solid #1e2329; }
            QTableWidget { background-color: #0b0e11; color: #eaecef; gridline-color: #1e2329; border: none; font-family: 'Consolas', monospace; }
            QHeaderView::section { background-color: #0b0e11; color: #5E6673; border: none; padding: 4px; font-size: 10px; font-weight: bold; }
            QTableWidget::item { padding: 4px; border-bottom: 1px solid #13171d; }
            QProgressBar { border: none; background: #13171d; height: 2px; }
            QProgressBar::chunk { background-color: #00F0FF; }
        """)

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet("background-color: #0b0e11; border: 1px solid #2b3139;")
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)

        # 1. Title Bar
        self.title_bar = ModernTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        # 2. Content Area
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        self.api_bar = QProgressBar()
        self.api_bar.setRange(0, config.RATE_LIMIT_CEILING)
        content_layout.addWidget(self.api_bar)

        # Table with 6 Quantitative columns
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["SYMBOL", "PRICE", "PROB %", "OI REGIME", "ALPHA / DIURNAL Z", "FLAGS / CONFLUENCE"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        content_layout.addWidget(self.table)

        # Legend
        legend = QLabel("■ >75%: SNIPER ALPHA   ■ >55%: MOMENTUM WATCHLIST   ■ <55%: ACCUMULATION / EARLY")
        legend.setStyleSheet("color: #444; font-size: 9px; font-family: 'Segoe UI'; font-weight: bold; letter-spacing: 1px;")
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(legend)

        self.main_layout.addLayout(content_layout)

        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)

        # Logic Thread
        self.scanner = AsyncExchange()
        self.scanner.data_signal.connect(self.update_table_view)
        self.scanner.status_signal.connect(self.title_bar.status_lbl.setText)
        self.scanner.weight_signal.connect(self.update_weight)
        self.scanner.timer_signal.connect(self.title_bar.timer_lbl.setText)
        self.scanner.start()

    def update_weight(self, w):
        self.api_bar.setValue(w)
        color = "#00F0FF" if w < 500 else "#FFD700" if w < 800 else "#FF0055"
        self.api_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

    def update_table_view(self, candidates: list):
        self.table.setRowCount(0)
        sorted_candidates = sorted(candidates, key=lambda x: x["probability"], reverse=True)

        for row_idx, data in enumerate(sorted_candidates):
            self.table.insertRow(row_idx)

            prob = data["probability"]
            if prob >= config.SNIPER_PROBABILITY_THRESHOLD:
                badge_color = "#00FFFF"  # Cyan Sniper Alpha
            elif prob >= config.WATCHLIST_PROBABILITY_THRESHOLD:
                badge_color = "#00FF66"  # Green Momentum
            else:
                badge_color = "#888888"  # Dark Gray Accumulation

            sym_item = QTableWidgetItem(data["symbol"])
            sym_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            sym_item.setForeground(QColor("#eaecef"))

            price_item = QTableWidgetItem(f"{data['price']:.4f}" if data['price'] < 10 else f"{data['price']:.2f}")
            price_item.setFont(QFont("Consolas", 9))
            price_item.setForeground(QColor("#b7bdc6"))

            prob_item = QTableWidgetItem(f"{prob:.1f}%")
            prob_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
            prob_item.setForeground(QColor(badge_color))
            prob_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            regime_item = QTableWidgetItem(f"{data['oi_regime']} (ΔOI: {data['delta_oi']:+.1f}%)")
            regime_item.setFont(QFont("Consolas", 8))
            if "AGG_LONG_INFLOW" in data['oi_regime']:
                regime_item.setForeground(QColor("#0ecb81"))
            elif "SHORT_COVERING" in data['oi_regime']:
                regime_item.setForeground(QColor("#00F0FF"))
            else:
                regime_item.setForeground(QColor("#848e9c"))

            alpha_item = QTableWidgetItem(f"α: {data['beta_alpha']:+.2f}% | Z: {data['diurnal_z']:.1f}")
            alpha_item.setFont(QFont("Consolas", 8))
            alpha_item.setForeground(QColor("#b7bdc6"))

            flags_item = QTableWidgetItem(" | ".join(data["flags"]))
            flags_item.setFont(QFont("Segoe UI", 8))
            if "SQUEEZE_FIRE" in data["flags"]:
                flags_item.setForeground(QColor("#00FFFF"))
            elif "COILED" in data["flags"]:
                flags_item.setForeground(QColor("#FF00FF"))
            else:
                flags_item.setForeground(QColor("#848e9c"))

            self.table.setItem(row_idx, 0, sym_item)
            self.table.setItem(row_idx, 1, price_item)
            self.table.setItem(row_idx, 2, prob_item)
            self.table.setItem(row_idx, 3, regime_item)
            self.table.setItem(row_idx, 4, alpha_item)
            self.table.setItem(row_idx, 5, flags_item)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._check_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.resizing:
            delta = event.globalPosition().toPoint() - self.old_pos
            self._resize_window(delta)
            self.old_pos = event.globalPosition().toPoint()
        else:
            edge = self._check_edge(event.pos())
            if edge in ("right", "left"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge in ("bottom", "top"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif edge == "bottom_right":
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.resize_edge = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _check_edge(self, pos):
        r = self.rect()
        m = self.grip_size
        x, y, w, h = pos.x(), pos.y(), r.width(), r.height()

        if x > w - m and y > h - m: return "bottom_right"
        if x > w - m: return "right"
        if y > h - m: return "bottom"
        if x < m: return "left"
        if y < m: return "top"
        return None

    def _resize_window(self, delta):
        geo = self.geometry()
        if self.resize_edge == "right":
            geo.setWidth(geo.width() + delta.x())
        elif self.resize_edge == "bottom":
            geo.setHeight(geo.height() + delta.y())
        elif self.resize_edge == "bottom_right":
            geo.setWidth(geo.width() + delta.x())
            geo.setHeight(geo.height() + delta.y())
        elif self.resize_edge == "left":
            geo.setLeft(geo.left() + delta.x())

        if geo.width() > 300 and geo.height() > 300:
            self.setGeometry(geo)

    def closeEvent(self, e):
        self.scanner.stop()
        self.scanner.wait()
        e.accept()


# Maintain BreakoutMonitor for backward compatibility / alias
BreakoutMonitor = BreakoutRadarWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = BreakoutRadarWindow()
    w.show()
    sys.exit(app.exec())
