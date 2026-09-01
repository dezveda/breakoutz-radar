import sys
import asyncio
import logging
from collections import deque
from typing import Dict, List, Optional, Type

import pandas as pd
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                              QHeaderView, QFrame, QPushButton)
from PyQt6.QtCore import pyqtSignal, QThread, Qt
from PyQt6.QtGui import QColor, QFont

from config import RadarConfig
from core.engine import BreakoutScoringEngine
from core.synthesis import fuse_exchange_results
from core.exchange_base import BaseExchangeFeed
from data.binance_feed import BinanceDataFeed
from data.bybit_feed import BybitDataFeed
from data.kucoin_feed import KucoinDataFeed
from data.okx_feed import OkxDataFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("BreakoutRadar")

FEED_CLASSES: Dict[str, Type[BaseExchangeFeed]] = {
    "BINANCE": BinanceDataFeed,
    "BYBIT": BybitDataFeed,
    "KUCOIN": KucoinDataFeed,
    "OKX": OkxDataFeed,
}

UNIFIED_COLUMNS = ["SYMBOL", "EXCHANGE", "PRICE", "SCORE", "DIRECTION", "ΔOI %", "FLAGS"]

# ==============================================================================
# PER-EXCHANGE WORKER THREAD
# ==============================================================================
class ExchangeWorker(QThread):
    """Owns one exchange's feed + rolling OHLCV buffers + scoring engine.
    Runs entirely on its own asyncio loop inside this QThread; talks to the
    UI thread only through Qt signals.
    """
    results_signal = pyqtSignal(str, dict)     # exchange_name, {symbol: row}
    status_signal = pyqtSignal(str, str)       # exchange_name, message

    def __init__(self, exchange_name: str, cfg: RadarConfig):
        super().__init__()
        self.exchange_name = exchange_name
        self.cfg = cfg
        self.feed: BaseExchangeFeed = FEED_CLASSES[exchange_name](cfg)
        self.engine = BreakoutScoringEngine(cfg)
        self.running = True
        self.buffers: Dict[str, deque] = {}
        self.oi_cache: Dict[str, List[float]] = {}
        self.latest_results: Dict[str, dict] = {}

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            logger.exception("%s worker crashed: %s", self.exchange_name, e)

    def stop(self):
        self.running = False
        self.feed.stop()

    async def _main(self):
        await self.feed.initialize()
        self.status_signal.emit(self.exchange_name, "DISCOVERING SYMBOLS...")

        symbols = await self.feed.fetch_active_usdt_pairs()
        if not symbols:
            self.status_signal.emit(self.exchange_name, "NO SYMBOLS — CHECK CONNECTIVITY")
            return

        # NOTE (known simplification): the original single-exchange scanner
        # pre-filtered by 24h quote volume via the ticker endpoint. Doing that
        # per-exchange here would add another bespoke REST call per adapter;
        # for now we just cap the raw active-pairs list. Re-introducing a
        # volume prefilter is a reasonable follow-up, not done in this pass.
        tracked = sorted(symbols)[: self.cfg.MAX_SYMBOLS_TRACKED]

        self.status_signal.emit(self.exchange_name, f"SEEDING {len(tracked)} SYMBOLS...")
        sem = asyncio.Semaphore(8)

        async def _seed(symbol: str):
            async with sem:
                df = await self.feed.fetch_historical_klines(symbol, self.cfg.KLINE_INTERVAL, self.cfg.LOOKBACK_PERIODS)
                if not df.empty:
                    self.buffers[symbol] = deque(df.to_dict("records"), maxlen=self.cfg.LOOKBACK_PERIODS)
                oi = await self.feed.fetch_open_interest_hist(symbol)
                if oi:
                    self.oi_cache[symbol] = oi

        await asyncio.gather(*(_seed(s) for s in tracked))
        self.status_signal.emit(self.exchange_name, "LIVE")

        oi_task = asyncio.create_task(self._oi_poll_loop(tracked, sem))
        try:
            await self.feed.listen_multiplex_kline_stream(tracked, self.cfg.KLINE_INTERVAL, self._on_kline_closed)
        finally:
            oi_task.cancel()

    async def _oi_poll_loop(self, symbols: List[str], sem: asyncio.Semaphore):
        while self.running:
            await asyncio.sleep(self.cfg.OI_POLL_SECONDS)

            async def _poll(symbol: str):
                async with sem:
                    oi = await self.feed.fetch_open_interest_hist(symbol)
                    if oi:
                        self.oi_cache[symbol] = oi

            await asyncio.gather(*(_poll(s) for s in symbols))

    async def _on_kline_closed(self, symbol: str, kline: dict):
        if not self.running:
            return
        buf = self.buffers.setdefault(symbol, deque(maxlen=self.cfg.LOOKBACK_PERIODS))
        buf.append(kline)
        if len(buf) < self.cfg.LOOKBACK_PERIODS // 2:
            return  # not enough history yet for a meaningful evaluation

        df = pd.DataFrame(list(buf))
        oi_hist = self.oi_cache.get(symbol, [])

        try:
            result = self.engine.evaluate_symbol(symbol, df, oi_hist)
        except Exception as e:
            logger.warning("%s evaluate_symbol(%s) failed: %s", self.exchange_name, symbol, e)
            return

        if result.get("score", 0) < self.cfg.DISPLAY_MIN_SCORE:
            self.latest_results.pop(symbol, None)
        else:
            self.latest_results[symbol] = result

        self.results_signal.emit(self.exchange_name, dict(self.latest_results))


# ==============================================================================
# UI
# ==============================================================================
class ModernTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 0, 0, 0)
        self.layout.setSpacing(0)

        self.title_lbl = QLabel("QUANT /// BREAKOUT RADAR")
        self.title_lbl.setStyleSheet("color: #00F0FF; font-family: 'Segoe UI'; font-weight: 900; font-size: 12px; letter-spacing: 2px;")
        self.layout.addWidget(self.title_lbl)
        self.layout.addStretch()

        self.status_lbl = QLabel("SYSTEM READY")
        self.status_lbl.setStyleSheet("color: #666; font-size: 10px; padding-right: 15px;")
        self.layout.addWidget(self.status_lbl)

        mode_style = """
            QPushButton { border: 1px solid #2b3139; background: #13171d; color: #00F0FF;
                          font-weight: 900; font-size: 10px; letter-spacing: 1px; padding: 4px 10px; }
            QPushButton:hover { background: #1e2329; }
        """
        self.mode_btn = QPushButton("MODE: —")
        self.mode_btn.setStyleSheet(mode_style)
        self.layout.addWidget(self.mode_btn)

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
        self.cfg = RadarConfig()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(920, 850)
        self.grip_size = 10
        self.resizing = False
        self.resize_edge = None

        self.setStyleSheet("""
            QMainWindow { background-color: #0b0e11; border: 1px solid #1e2329; }
            QTableWidget { background-color: #0b0e11; color: #eaecef; gridline-color: #1e2329; border: none; font-family: 'Consolas', monospace; }
            QHeaderView::section { background-color: #0b0e11; color: #5E6673; border: none; padding: 4px; font-size: 10px; font-weight: bold; }
            QTableWidget::item { padding: 4px; border-bottom: 1px solid #13171d; }
        """)

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet("background-color: #0b0e11; border: 1px solid #2b3139;")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)

        self.title_bar = ModernTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        self.table = QTableWidget()
        self.table.setColumnCount(len(UNIFIED_COLUMNS))
        self.table.setHorizontalHeaderLabels(UNIFIED_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        for col in range(len(UNIFIED_COLUMNS) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(UNIFIED_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        content_layout.addWidget(self.table)

        legend = QLabel("■ >75: SNIPER ■ >55: WATCHLIST ■ <55: EARLY   |   Modo: exchange individual → SÍNTESIS (botón superior)")
        legend.setStyleSheet("color: #444; font-size: 9px; font-family: 'Segoe UI'; font-weight: bold; letter-spacing: 1px;")
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(legend)

        self.main_layout.addLayout(content_layout)
        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)

        # ---- Multi-exchange mode state ----
        self.exchange_names: List[str] = list(self.cfg.EXCHANGES.keys())
        self.mode_names: List[str] = self.exchange_names + ["SÍNTESIS"]
        self.mode_idx = 0
        self.title_bar.mode_btn.setText(f"MODE: {self.mode_names[self.mode_idx]}")
        self.title_bar.mode_btn.clicked.connect(self._cycle_mode)

        self.results_by_exchange: Dict[str, Dict[str, dict]] = {name: {} for name in self.exchange_names}
        self.exchange_status: Dict[str, str] = {name: "STARTING..." for name in self.exchange_names}
        self._displayed_symbols: List[str] = []  # for the diff-update, avoids full rebuild every tick

        self.workers: List[ExchangeWorker] = []
        for name in self.exchange_names:
            worker = ExchangeWorker(name, self.cfg)
            worker.results_signal.connect(self._on_results)
            worker.status_signal.connect(self._on_status)
            self.workers.append(worker)
            worker.start()

    # ---- Mode switching ----
    def _cycle_mode(self):
        self.mode_idx = (self.mode_idx + 1) % len(self.mode_names)
        self.title_bar.mode_btn.setText(f"MODE: {self.mode_names[self.mode_idx]}")
        self._render()

    def _current_rows(self) -> List[dict]:
        mode = self.mode_names[self.mode_idx]
        if mode == "SÍNTESIS":
            return fuse_exchange_results(self.results_by_exchange, self.cfg)
        rows = sorted(self.results_by_exchange.get(mode, {}).values(), key=lambda r: r["score"], reverse=True)
        return [dict(r, exchanges=[mode]) for r in rows]

    # ---- Signal handlers ----
    def _on_results(self, exchange_name: str, results: dict):
        self.results_by_exchange[exchange_name] = results
        self._render()

    def _on_status(self, exchange_name: str, message: str):
        self.exchange_status[exchange_name] = message
        live_count = sum(1 for s in self.exchange_status.values() if s == "LIVE")
        self.title_bar.status_lbl.setText(f"{live_count}/{len(self.exchange_names)} EXCHANGES LIVE — {exchange_name}: {message}")

    # ---- Rendering (diff-update: only full rebuild when the symbol set changes) ----
    def _render(self):
        rows = self._current_rows()
        new_symbols = [r["symbol"] for r in rows]

        if new_symbols != self._displayed_symbols:
            self.table.setRowCount(0)
            for _ in rows:
                self.table.insertRow(self.table.rowCount())
            self._displayed_symbols = new_symbols

        for row_idx, data in enumerate(rows):
            self._paint_row(row_idx, data)

    def _paint_row(self, row_idx: int, data: dict):
        score = data["score"]
        if score >= self.cfg.SCORE_SNIPER:
            badge_color = "#00FFFF"
        elif score >= self.cfg.SCORE_WATCHLIST:
            badge_color = "#00FF66"
        else:
            badge_color = "#888888"

        sym_item = QTableWidgetItem(data["symbol"])
        sym_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        sym_item.setForeground(QColor("#eaecef"))

        exch_label = "+".join(data.get("exchanges", ["?"]))
        exch_item = QTableWidgetItem(exch_label)
        exch_item.setFont(QFont("Consolas", 8))
        exch_item.setForeground(QColor("#00F0FF") if len(data.get("exchanges", [])) > 1 else QColor("#848e9c"))

        price = data.get("price")
        price_item = QTableWidgetItem("—" if price is None else (f"{price:.4f}" if price < 10 else f"{price:.2f}"))
        price_item.setFont(QFont("Consolas", 9))
        price_item.setForeground(QColor("#b7bdc6"))

        score_item = QTableWidgetItem(f"{score}")
        score_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
        score_item.setForeground(QColor(badge_color))
        score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        direction = data["direction"]
        dir_item = QTableWidgetItem(direction)
        dir_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        dir_item.setForeground(QColor("#0ecb81") if direction == "LONG" else QColor("#ff3333") if direction == "SHORT" else QColor("#848e9c"))

        oi_item = QTableWidgetItem(f"{data.get('delta_oi', 0.0):+.1f}%")
        oi_item.setFont(QFont("Consolas", 8))
        oi_item.setForeground(QColor("#b7bdc6"))

        flags_item = QTableWidgetItem(" | ".join(data.get("flags", [])))
        flags_item.setFont(QFont("Segoe UI", 8))
        flags_item.setForeground(QColor("#FF00FF") if "CROSS_CONFIRMED" in data.get("flags", []) else QColor("#848e9c"))

        for col, item in enumerate([sym_item, exch_item, price_item, score_item, dir_item, oi_item, flags_item]):
            self.table.setItem(row_idx, col, item)

    # ---- Frameless window drag/resize (unchanged from prior version) ----
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
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.wait(3000)
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = BreakoutRadarWindow()
    w.show()
    sys.exit(app.exec())
