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
# CAPA DE DATOS: ARQUITECTURA RADAR + LÓGICA DEZ v3
# ==============================================================================
class AsyncExchange(QThread):
    data_signal = pyqtSignal(list)
    status_signal = pyqtSignal(str)
    weight_signal = pyqtSignal(int)
    timer_signal = pyqtSignal(str) # Nueva señal para feedback visual de vida

    def __init__(self):
        super().__init__()
        self.running = True
        self.used_weight = 0
        
    async def get_json(self, session, url, params=None):
        try:
            async with session.get(url, params=params, timeout=8) as resp:
                w = resp.headers.get('X-MBX-USED-WEIGHT-1M')
                if w: 
                    self.used_weight = int(w)
                    self.weight_signal.emit(self.used_weight)
                
                if resp.status == 429:
                    self.status_signal.emit("⚠️ RATELIMIT! PAUSING 60s...")
                    await asyncio.sleep(60)
                    return None
                if resp.status >= 500: return None
                return await resp.json()
        except: return None

    async def fetch_candles(self, session, symbol):
        # Usamos 1h para estructura macro (Trend)
        df_macro = await self.get_json(session, "https://fapi.binance.com/fapi/v1/klines", 
                                     {'symbol': symbol, 'interval': '1h', 'limit': 48})
        # Usamos 15m para estructura micro (Power Factor / Squeeze)
        df_micro = await self.get_json(session, "https://fapi.binance.com/fapi/v1/klines", 
                                     {'symbol': symbol, 'interval': '15m', 'limit': 24})
        
        if not df_macro or not df_micro: return None, None
        
        d_ma = pd.DataFrame(df_macro, dtype=float).iloc[:, :6]
        d_ma.columns = ['ts', 'o', 'h', 'l', 'c', 'v']
        
        d_mi = pd.DataFrame(df_micro, dtype=float).iloc[:, :6]
        d_mi.columns = ['ts', 'o', 'h', 'l', 'c', 'v']
        
        return d_ma, d_mi

    async def analyze_ticker(self, session, ticker):
        """
        SCIENTIFIC UPGRADE: Detección de Transición de Fase (Compresión -> Expansión).
        Busca anomalías estadísticas (Z-Score) en volumen sobre estructuras de baja volatilidad.
        """
        symbol = ticker['symbol']
        try:
            vol_24h = float(ticker['quoteVolume'])
            pct_24h = float(ticker['priceChangePercent'])
            last_price = float(ticker['lastPrice'])
        except: return None

        # Filtros básicos
        if vol_24h < CONF['MIN_VOL_24H'] or symbol in CONF['BLACKLIST']: return None
        if "USDT" not in symbol: return None

        # Fetch Profundo
        df_macro, df_micro = await self.fetch_candles(session, symbol)
        if df_macro is None: return None

        score = 0.0
        details = []

        # --- 1. VOLUME Z-SCORE (Anomalía Estadística) ---
        # Si el volumen es viejo, no sirve.
        vol_recent = df_macro['v'].iloc[-4:].sum()
        vol_total = df_macro['v'].sum()
        freshness = (vol_recent / (vol_total + 1e-9)) * 100
        
        if freshness < 10: return None # Descartar zombies
        
        # Calculamos si el volumen actual es una anomalía estadística (Z-Score > 2)
        vols = df_macro['v'].values
        vol_mean = np.mean(vols)
        vol_std = np.std(vols)
        vol_z = (vols[-1] - vol_mean) / (vol_std + 1e-9)
        
        if vol_z > 3.0: score += 25; details.append("VOL_SPIKE")
        elif vol_z > 1.5: score += 10

        # --- 2. VOLATILITY COMPRESSION (La Energía Potencial) ---
        # Usamos Bollinger Band Width (BBW) normalizado para detectar el "Squeeze" antes del disparo
        closes_macro = df_macro['c'].values
        bb_std = np.std(closes_macro[-20:]) 
        bb_ma = np.mean(closes_macro[-20:])
        bbw = (4 * bb_std) / bb_ma # Ancho de banda relativo
        
        # Si la volatilidad histórica es extremadamente baja (< 2%), el movimiento será violento
        if bbw < 0.03: 
            score += 20
            details.append("COILED") # Resorte comprimido

        # --- 3. MICRO-STRUCTURE BREAKOUT (15m) ---
        last_candle = df_micro.iloc[-2] # Penúltima (cerrada)
        curr_candle = df_micro.iloc[-1] # Actual (en formación)
        
        price_move_pct = abs((curr_candle['c'] - curr_candle['o']) / curr_candle['o'] * 100)
        
        # Power Candle: Cuerpo grande sin mechas
        upper_wick = (curr_candle['h'] - max(curr_candle['c'], curr_candle['o']))
        total_len = (curr_candle['h'] - curr_candle['l'])
        body_len = abs(curr_candle['c'] - curr_candle['o'])
        
        if total_len > 0:
            if (body_len / total_len) > 0.7 and price_move_pct > 0.5:
                score += 15
                details.append("MOMENTUM")
            elif (upper_wick / total_len) > 0.6: 
                score -= 30 # Rechazo/Venta fuerte

        # --- 4. TREND ALIGNMENT (SMA 1H) ---
        sma7 = np.mean(closes_macro[-7:])
        sma25 = np.mean(closes_macro[-25:])
        
        if sma7 > sma25:
            score += 15 # Tendencia alcista
            if last_price > df_macro['h'].max() * 0.99: # Cerca del máximo
                score += 10
                details.append("ATH_NEAR")
        else:
            if pct_24h > 5.0: score -= 10 # Reversión contra tendencia (peligroso)

        # --- 5. OPEN INTEREST (Solo para candidatos TOP) ---
        # Optimizamos API: Solo chequeamos OI si el score ya promete (>30)
        oi_change = 0.0
        if score > 30:
            try:
                oi_data = await self.get_json(session, "https://fapi.binance.com/fapi/v1/openInterest", {'symbol': symbol})
                if oi_data:
                    # No podemos calcular cambio real sin historial, pero validamos que exista OI sustancial
                    oi_val = float(oi_data['openInterest'])
                    if oi_val > 0: score += 10 # Bonificación por tener mercado de futuros activo
            except: pass

        # Normalización final
        score = max(0, min(100, score))

        return {
            'symbol': symbol,
            'price': last_price,
            'change': pct_24h,
            'vol_m': vol_24h / 1_000_000,
            'score': score,
            'details': " ".join(details)
        }

    async def run_loop(self):
        # Sesión persistente para evitar fugas de memoria y sockets
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # 1. Chequeo de Salud API
                    if self.used_weight > CONF['API_WEIGHT_LIMIT']:
                        self.status_signal.emit(f"⏳ API COOLING ({self.used_weight})...")
                        await asyncio.sleep(10)
                        continue

                    self.status_signal.emit("🔍 GLOBAL SCAN IN PROGRESS...")
                    
                    # 2. Ingesta Global
                    tickers = await self.get_json(session, "https://fapi.binance.com/fapi/v1/ticker/24hr")
                    if not tickers:
                        await asyncio.sleep(5); continue

                    # 3. Pre-filtro (Optimizado)
                    candidates = []
                    for t in tickers:
                        try:
                            v = float(t['quoteVolume'])
                            # Solo analizamos activos con liquidez real para evitar trampas
                            if v > CONF['MIN_VOL_24H']: candidates.append(t)
                        except: continue
                    
                    # Ordenar por 'Interés' (Volatilidad * Volumen)
                    candidates.sort(key=lambda x: float(x['quoteVolume']) * abs(float(x['priceChangePercent'])), reverse=True)
                    target_candidates = candidates[:40] # Analizamos Top 40

                    self.status_signal.emit(f"🔬 COMPUTING METRICS ON {len(target_candidates)} ASSETS...")
                    
                    results = []
                    sem = asyncio.Semaphore(CONF['MAX_CONCURRENT_REQ'])

                    async def bound_analyze(t):
                        async with sem: return await self.analyze_ticker(session, t)

                    tasks = [bound_analyze(t) for t in target_candidates]
                    for f in asyncio.as_completed(tasks):
                        res = await f
                        if res and res['score'] > 25: # Umbral de calidad mínima
                            results.append(res)
                    
                    # Ordenar por Probabilidad de Breakout (Score)
                    results.sort(key=lambda x: x['score'], reverse=True)
                    
                    self.data_signal.emit(results)
                    self.status_signal.emit(f"✅ FOUND {len(results)} OPPORTUNITIES")
              
                except Exception as e:
                    self.status_signal.emit(f"⚠️ NETWORK ERROR: {str(e)} - RETRYING...")
                    await asyncio.sleep(5)
                
                # Smart Sleep con Feedback Visual
                for i in range(CONF['REFRESH_RATE'], 0, -1):
                    if not self.running: break
                    self.timer_signal.emit(f"NEXT SCAN: {i}s")
                    await asyncio.sleep(1)

    def run(self): asyncio.run(self.run_loop())
    def stop(self): self.running = False

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

        # Timer Label (Nueva adición)
        self.timer_lbl = QLabel("")
        self.timer_lbl.setStyleSheet("color: #00F0FF; font-size: 10px; font-weight: bold; padding-right: 10px;")
        self.layout.insertWidget(2, self.timer_lbl) # Insertar antes del status

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
        self.main_layout.setContentsMargins(1, 1, 1, 1) # Borde para ver el outline
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
        self.scanner.timer_signal.connect(self.title_bar.timer_lbl.setText) # Conectar Timer
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
            if "COILED" in dets: flags.setForeground(QColor("#FF00FF")) # Magenta para alta tensión
            elif "VOL_SPIKE" in dets: flags.setForeground(QColor("#00F0FF")) # Cyan para volumen
            elif "MOMENTUM" in dets: flags.setForeground(QColor("#0ecb81")) # Verde para fuerza
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

    # --- LÓGICA DE REDIMENSIONADO ESTABLE (PYTHON PURO) ---
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
            # Cambiar cursor según posición
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
        # Detectar si el mouse está en los bordes
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
        
        # Mínimos
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