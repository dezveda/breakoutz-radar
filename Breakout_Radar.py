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

from config import RadarConfig
from core.engine import BreakoutScoringEngine
from data.binance_feed import BinanceDataFeed

# ==============================================================================
# CONFIGURACIÓN (SMART MONEY EDITION)
# ==============================================================================
CONF = {
    'MIN_VOL_24H': 15_000_000,   # Subido a 15M para evitar ruido
    'BLACKLIST': ['USDCUSDT', 'BUSDUSDT', 'TUSDUSDT', 'USDPUSDT', 'FDUSDUSDT'],
    'REFRESH_RATE': 45,          # Más rápido
    'MAX_CONCURRENT_REQ': 8,     # Más agresivo
    'API_WEIGHT_LIMIT': 1100     # Límite Binance es 1200
}

# ==============================================================================
# CAPA DE DATOS: INTEGRACIÓN BINANCE FEED + BREAKOUT ENGINE
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
        self.cfg = RadarConfig()
        self.feed = BinanceDataFeed(self.cfg)
        self.engine = BreakoutScoringEngine(self.cfg)

    async def get_24h_tickers(self):
        url = f"{self.cfg.BINANCE_REST_BASE}/fapi/v1/ticker/24hr"
        try:
            async with self.feed.session.get(url, timeout=8) as resp:
                w = resp.headers.get('X-MBX-USED-WEIGHT-1M')
                if w:
                    self.used_weight = int(w)
                    self.weight_signal.emit(self.used_weight)

                if resp.status == 429:
                    self.status_signal.emit("⚠️ RATELIMIT! PAUSING 60s...")
                    await asyncio.sleep(60)
                    return None
                if resp.status >= 500:
                    return None
                return await resp.json()
        except Exception:
            return None

    async def fetch_open_interest(self, symbol: str) -> list[float]:
        url = f"{self.cfg.BINANCE_REST_BASE}/fapi/v1/openInterest"
        try:
            async with self.feed.session.get(url, params={'symbol': symbol}, timeout=5) as resp:
                w = resp.headers.get('X-MBX-USED-WEIGHT-1M')
                if w:
                    self.used_weight = int(w)
                    self.weight_signal.emit(self.used_weight)
                if resp.status == 200:
                    data = await resp.json()
                    oi_val = float(data.get('openInterest', 0))
                    if oi_val > 0:
                        return [oi_val * 0.97, oi_val]
        except Exception:
            pass
        return []

    async def analyze_ticker(self, ticker: dict):
        symbol = ticker['symbol']
        try:
            vol_24h = float(ticker['quoteVolume'])
            pct_24h = float(ticker['priceChangePercent'])
            last_price = float(ticker['lastPrice'])
        except Exception:
            return None

        if vol_24h < CONF['MIN_VOL_24H'] or symbol in CONF['BLACKLIST']:
            return None
        if "USDT" not in symbol:
            return None

        df_fast = await self.feed.fetch_historical_klines(symbol, interval=self.cfg.TIMEFRAME_FAST, limit=50)
        if df_fast.empty or len(df_fast) < self.cfg.LOOKBACK_PERIODS:
            return None

        historical_oi = await self.fetch_open_interest(symbol)

        res = self.engine.evaluate_symbol(symbol, df_fast, historical_oi)
        score = res.get('score', 0)
        if score <= 25:
            return None

        flags = res.get('flags', [])
        details = " ".join(flags)

        return {
            'symbol': symbol,
            'price': last_price,
            'change': pct_24h,
            'vol_m': vol_24h / 1_000_000,
            'score': score,
            'details': details
        }

    async def run_loop(self):
        await self.feed.initialize()
        try:
            while self.running:
                try:
                    if self.used_weight > CONF['API_WEIGHT_LIMIT']:
                        self.status_signal.emit(f"⏳ API COOLING ({self.used_weight})...")
                        await asyncio.sleep(10)
                        continue

                    self.status_signal.emit("🔍 GLOBAL SCAN IN PROGRESS...")

                    tickers = await self.get_24h_tickers()
                    if not tickers:
                        await asyncio.sleep(5)
                        continue

                    candidates = []
                    for t in tickers:
                        try:
                            v = float(t['quoteVolume'])
                            if v > CONF['MIN_VOL_24H']:
                                candidates.append(t)
                        except Exception:
                            continue

                    candidates.sort(key=lambda x: float(x['quoteVolume']) * abs(float(x['priceChangePercent'])), reverse=True)
                    target_candidates = candidates[:40]

                    self.status_signal.emit(f"🔬 COMPUTING METRICS ON {len(target_candidates)} ASSETS...")

                    results = []
                    sem = asyncio.Semaphore(CONF['MAX_CONCURRENT_REQ'])

                    async def bound_analyze(t):
                        async with sem:
                            return await self.analyze_ticker(t)

                    tasks = [bound_analyze(t) for t in target_candidates]
                    for f in asyncio.as_completed(tasks):
                        res = await f
                        if res and res['score'] > 25:
                            results.append(res)

                    results.sort(key=lambda x: x['score'], reverse=True)

                    self.data_signal.emit(results)
                    self.status_signal.emit(f"✅ FOUND {len(results)} OPPORTUNITIES")

                except Exception as e:
                    self.status_signal.emit(f"⚠️ NETWORK ERROR: {str(e)} - RETRYING...")
                    await asyncio.sleep(5)

                for i in range(CONF['REFRESH_RATE'], 0, -1):
                    if not self.running:
                        break
                    self.timer_signal.emit(f"NEXT SCAN: {i}s")
                    await asyncio.sleep(1)
        finally:
            await self.feed.close()

    def run(self):
        asyncio.run(self.run_loop())

    def stop(self):
        self.running = False

# ==============================================================================
# UI (VISUALIZACIÓN TÁCTICA - FRAMELESS & RESIZABLE)
# ==============================================================================
class ModernTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 0, 0, 0)
        self.layout.setSpacing(0)

        # Title / Logo area
        self.title_lbl = QLabel("VECTOR /// RADAR")
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

        # Draggable Logic
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

class BreakoutMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(650, 850)

        # Variables de redimensionado
        self.grip_size = 10
        self.resizing = False
        self.resize_edge = None
        self.old_pos = None

        # Styles
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0e11; border: 1px solid #1e2329; }
            QTableWidget { background-color: #0b0e11; color: #eaecef; gridline-color: #1e2329; border: none; font-family: 'Consolas', monospace; }
            QHeaderView::section { background-color: #0b0e11; color: #5E6673; border: none; padding: 4px; font-size: 10px; font-weight: bold; }
            QTableWidget::item { padding: 4px; border-bottom: 1px solid #13171d; }
            QProgressBar { border: none; background: #13171d; height: 2px; }
            QProgressBar::chunk { background-color: #00F0FF; }
        """)

        # Main Layout Wrapper
        self.central_widget = QWidget()
        self.central_widget.setStyleSheet("background-color: #0b0e11; border: 1px solid #2b3139;")
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)

        # 1. Custom Title Bar
        self.title_bar = ModernTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        # 2. Content Area
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        # API Weight Bar
        self.api_bar = QProgressBar()
        self.api_bar.setRange(0, 1200)
        content_layout.addWidget(self.api_bar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ASSET", "PRICE", "24h %", "VOL (M)", "SIGNAL", "SCORE"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Header setup
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        content_layout.addWidget(self.table)

        # Legend
        legend = QLabel("■ >80: SNIPER ENTRY   ■ >60: WATCHLIST   ■ <60: NO TRADE")
        legend.setStyleSheet("color: #444; font-size: 9px; font-family: 'Segoe UI'; font-weight: bold; letter-spacing: 1px;")
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(legend)

        self.main_layout.addLayout(content_layout)

        # Habilitar tracking del mouse para cambiar el cursor en los bordes
        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)

        # Logic Thread
        self.scanner = AsyncExchange()
        self.scanner.data_signal.connect(self.update_table)
        self.scanner.status_signal.connect(self.title_bar.status_lbl.setText)
        self.scanner.weight_signal.connect(self.update_weight)
        self.scanner.timer_signal.connect(self.title_bar.timer_lbl.setText)
        self.scanner.start()

    def update_weight(self, w):
        self.api_bar.setValue(w)
        color = "#00F0FF" if w < 600 else "#FFD700" if w < 1000 else "#FF0055"
        self.api_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

    def update_table(self, data):
        self.table.setRowCount(len(data))
        for i, row in enumerate(data):
            font_main = QFont("Segoe UI", 9, QFont.Weight.Bold)
            font_num = QFont("Consolas", 9)

            sym = QTableWidgetItem(row['symbol'].replace("USDT",""))
            sym.setFont(font_main)
            sym.setForeground(QColor("#eaecef"))
            self.table.setItem(i, 0, sym)

            p_val = f"{row['price']:.4f}" if row['price'] < 10 else f"{row['price']:.2f}"
            price = QTableWidgetItem(p_val)
            price.setFont(font_num)
            price.setForeground(QColor("#b7bdc6"))
            self.table.setItem(i, 1, price)

            pct = row['change']
            change = QTableWidgetItem(f"{pct:+.2f}%")
            change.setFont(font_num)
            c_color = "#0ecb81" if pct > 0 else "#f6465d"
            change.setForeground(QColor(c_color))
            self.table.setItem(i, 2, change)

            vol = QTableWidgetItem(f"{row['vol_m']:.1f}M")
            vol.setFont(font_num)
            vol.setForeground(QColor("#848e9c"))
            self.table.setItem(i, 3, vol)

            dets = row['details']
            flags = QTableWidgetItem(dets)
            flags.setFont(QFont("Segoe UI", 8))
            if "COILED" in dets: flags.setForeground(QColor("#FF00FF"))
            elif "VOL_SPIKE" in dets: flags.setForeground(QColor("#00F0FF"))
            elif "MOMENTUM" in dets: flags.setForeground(QColor("#0ecb81"))
            else: flags.setForeground(QColor("#5E6673"))
            self.table.setItem(i, 4, flags)

            sc = row['score']
            s_item = QTableWidgetItem(f"{sc:.0f}")
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            s_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
            if sc >= 80:
                s_item.setForeground(QColor("#00F0FF"))
                s_item.setBackground(QColor(0, 240, 255, 25))
            elif sc >= 60:
                s_item.setForeground(QColor("#0ecb81"))
            else:
                s_item.setForeground(QColor("#444"))
            self.table.setItem(i, 5, s_item)

    # --- LÓGICA DE REDIMENSIONADO ESTABLE ---
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
            if edge == "right" or edge == "left":
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge == "bottom" or edge == "top":
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = BreakoutMonitor()
    w.show()
    sys.exit(app.exec())
