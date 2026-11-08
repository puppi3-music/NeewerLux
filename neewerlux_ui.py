"""NeewerLux main window UI.

Builds the widget tree and layouts. Widget attribute names are the
contract with NeewerLux.py, which connects the signal handlers.
"""

import re

try:
    import PySide6
    from PySide6.QtCore import Qt, Signal, QSize
    from PySide6.QtGui import QFont, QColor, QLinearGradient, QBrush, QKeySequence, QIcon, QPainter, QConicalGradient, QRadialGradient, QPen, QGuiApplication
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
        QSplitter, QSizePolicy, QAbstractItemView, QAbstractScrollArea,
        QPushButton, QLabel, QSlider, QTableWidget, QTableWidgetItem,
        QTabWidget, QCheckBox, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QAbstractButton,
        QGraphicsView, QGraphicsScene, QScrollArea, QKeySequenceEdit,
        QListWidget, QListWidgetItem, QStatusBar, QHeaderView, QFrame, QProgressBar,
        QSystemTrayIcon, QMenu, QTextBrowser, QColorDialog, QDialog, QDialogButtonBox
    )
    customSignal = Signal
except ImportError:
    try:
        import PySide2
        from PySide2.QtCore import Qt, Signal, QSize
        from PySide2.QtGui import QFont, QColor, QLinearGradient, QBrush, QKeySequence, QIcon, QPainter, QConicalGradient, QRadialGradient, QPen, QGuiApplication
        from PySide2.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
            QSplitter, QSizePolicy, QAbstractItemView, QAbstractScrollArea,
            QPushButton, QLabel, QSlider, QTableWidget, QTableWidgetItem,
            QTabWidget, QCheckBox, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QAbstractButton,
            QGraphicsView, QGraphicsScene, QScrollArea, QKeySequenceEdit,
            QListWidget, QListWidgetItem, QStatusBar, QHeaderView, QFrame, QProgressBar,
            QSystemTrayIcon, QMenu, QTextBrowser, QColorDialog, QDialog, QDialogButtonBox
        )
        customSignal = Signal
    except ImportError:
        raise  # let it propagate, NeewerLux.py will handle the error


# === HELPER WIDGETS ===

class SpinBoxWithButtons(QWidget):
    """QSpinBox with external +/- buttons to avoid overlap issues at high DPI."""
    valueChanged = customSignal(int)

    def __init__(self, parent=None, minVal=0, maxVal=100, value=0, suffix=""):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self._spin = QSpinBox()
        self._spin.setRange(minVal, maxVal)
        self._spin.setValue(value)
        if suffix:
            self._spin.setSuffix(suffix)
        self._spin.setButtonSymbols(QSpinBox.NoButtons)
        self._spin.valueChanged.connect(self.valueChanged.emit)

        btnStyle = "QPushButton { font-size: 14px; font-weight: bold; min-width: 28px; }"
        self._minus = QPushButton("-")
        self._minus.setStyleSheet(btnStyle)
        self._minus.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._minus.setFixedWidth(30)
        self._minus.clicked.connect(lambda: self._spin.setValue(self._spin.value() - self._spin.singleStep()))
        self._plus = QPushButton("+")
        self._plus.setStyleSheet(btnStyle)
        self._plus.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._plus.setFixedWidth(30)
        self._plus.clicked.connect(lambda: self._spin.setValue(self._spin.value() + self._spin.singleStep()))

        lay.addWidget(self._spin, 1)
        lay.addWidget(self._minus)
        lay.addWidget(self._plus)

    def value(self):
        return self._spin.value()

    def setValue(self, v):
        self._spin.setValue(v)

    def setRange(self, lo, hi):
        self._spin.setRange(lo, hi)

    def setSuffix(self, s):
        self._spin.setSuffix(s)

    def setSingleStep(self, s):
        self._spin.setSingleStep(s)

    def setToolTip(self, t):
        self._spin.setToolTip(t)
        self._minus.setToolTip(t)
        self._plus.setToolTip(t)

    def setMinimumWidth(self, w):
        self._spin.setMinimumWidth(w)


class customPresetButton(QPushButton):
    rightclicked = customSignal()
    middleclicked = customSignal()
    enteredWidget = customSignal()
    leftWidget = customSignal()

    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self.setText(text)
        self.setProperty("presetButton", True)
        self.setProperty("presetType", "default")

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightclicked.emit()
        elif event.button() == Qt.MiddleButton:
            self.middleclicked.emit()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        self.enteredWidget.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.leftWidget.emit()
        super().leaveEvent(event)

    def markCustom(self, presetNum, isSnap=0, presetName=""):
        """Update the button display text and type property for QSS styling.
        isSnap: 0 = custom global, >=1 = snapshot, <0 = reset to default."""
        nameLabel = presetName if presetName else ""
        numStr = str(presetNum + 1)

        if isSnap == 0:  # custom global preset
            if nameLabel:
                self.setText(numStr + "\n" + nameLabel[:16])
            else:
                self.setText(numStr + "\nCUSTOM\nGLOBAL")
            self.setProperty("presetType", "global")
        elif isSnap >= 1:  # snapshot preset
            if nameLabel:
                self.setText(numStr + "\n" + nameLabel[:16])
            else:
                self.setText(numStr + "\nCUSTOM\nSNAP")
            self.setProperty("presetType", "snap")
        else:  # reset to default
            if nameLabel:
                self.setText(numStr + "\n" + nameLabel[:16])
            else:
                self.setText(numStr + "\nPRESET\nGLOBAL")
            self.setProperty("presetType", "default")

        # Force QSS refresh for the new property value
        self.style().unpolish(self)
        self.style().polish(self)


def _monoFont(pointSize=9):
    """Monospace font with fallbacks, matching the theme's mono stack."""
    f = QFont("Consolas", pointSize)
    f.setStyleHint(QFont.Monospace)
    f.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"])
    return f


class singleKeySequenceEditCancel(QWidget):
    def __init__(self, defaultValue=""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.defaultValue = defaultValue
        self.keySequence = QKeySequence(defaultValue)
        self.keyPressField = QKeySequenceEdit(self.keySequence)
        self.keyPressField.setMinimumWidth(150)
        # Qt draws an internal clear button that renders as an empty square on this theme.
        # The external X button below covers the same job.
        for _btn in self.keyPressField.findChildren(QAbstractButton):
            _btn.setFixedSize(0, 0)
            _btn.setVisible(False)
        self.keyPressField.keySequenceChanged.connect(self._onChanged)
        lay.addWidget(self.keyPressField)
        resetBtn = QPushButton("X")
        resetBtn.setFixedWidth(24)
        resetBtn.clicked.connect(self.resetValue)
        lay.addWidget(resetBtn)

    def _onChanged(self, seq):
        self.keySequence = seq

    def resetValue(self):
        self.keySequence = QKeySequence(self.defaultValue)
        self.keyPressField.setKeySequence(self.keySequence)

    def setKeySequence(self, seq):
        self.keySequence = QKeySequence(seq) if isinstance(seq, str) else seq
        self.keyPressField.setKeySequence(self.keySequence)

    def getKeySequence(self):
        """Return the current key sequence string from the underlying edit field."""
        return self.keyPressField.keySequence().toString()


class GradientBar(QWidget):
    """A widget that paints a linear gradient that always fills its full width."""
    def __init__(self, stops, parent=None):
        """stops: list of (position, QColor) tuples, e.g. [(0.0, QColor(255,0,0)), (1.0, QColor(0,0,255))]"""
        super().__init__(parent)
        self._stops = stops
        self.setMinimumHeight(16)
        self.setMaximumHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setStops(self, stops):
        self._stops = stops
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), 0)
        for pos, color in self._stops:
            grad.setColorAt(pos, color)
        p.fillRect(self.rect(), grad)
        p.end()


def _makeGradientBar(stops):
    """Create a GradientBar from a list of (position, QColor) tuples."""
    return GradientBar(stops)


class GradientSlider(QWidget):
    """A slider with a gradient bar above it and min/max endpoint labels below.
    Uses a grid layout so gradient, slider groove, and labels all share the same column width."""
    valueChanged = customSignal(int)

    def __init__(self, minVal=0, maxVal=100, value=50, suffix="",
                 gradientStops=None, minLabel="", maxLabel="", parent=None):
        super().__init__(parent)
        self._suffix = suffix
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        grid.setColumnStretch(0, 1)  # gradient/slider column expands
        grid.setColumnStretch(1, 0)  # value label column stays fixed

        # Row 0: gradient bar | value label
        if gradientStops:
            self._gradient = GradientBar(gradientStops)
        else:
            self._gradient = GradientBar([(0, QColor(128, 128, 128)), (1, QColor(200, 200, 200))])
        grid.addWidget(self._gradient, 0, 0)
        self._valLabel = QLabel(str(value) + suffix)
        self._valLabel.setFixedWidth(60)
        self._valLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f = QFont(); f.setBold(True); self._valLabel.setFont(f)
        grid.addWidget(self._valLabel, 0, 1)

        # Row 1: slider (spans only column 0 so it matches gradient width)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(minVal, maxVal)
        self._slider.setValue(value)
        self._slider.setMinimumHeight(18)
        self._slider.valueChanged.connect(self._onChanged)
        grid.addWidget(self._slider, 1, 0)

        # Row 2: min/max labels (column 0 only)
        mmW = QWidget()
        mmRow = QHBoxLayout(mmW)
        mmRow.setContentsMargins(0, 0, 0, 0)
        self._minLabel = QLabel(minLabel or str(minVal))
        sf = QFont(); sf.setPointSize(8)
        self._minLabel.setFont(sf)
        self._minLabel.setAlignment(Qt.AlignLeft)
        self._maxLabel = QLabel(maxLabel or str(maxVal))
        self._maxLabel.setFont(sf)
        self._maxLabel.setAlignment(Qt.AlignRight)
        mmRow.addWidget(self._minLabel)
        mmRow.addStretch(1)
        mmRow.addWidget(self._maxLabel)
        grid.addWidget(mmW, 2, 0)

        # Column stretch: slider/gradient column expands, value label fixed
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)

    def _onChanged(self, v):
        self._valLabel.setText(str(v) + self._suffix)
        self.valueChanged.emit(v)

    def value(self):
        return self._slider.value()

    def setValue(self, v):
        self._slider.setValue(v)

    def setRange(self, lo, hi):
        self._slider.setRange(lo, hi)
        self._minLabel.setText(str(lo))
        self._maxLabel.setText(str(hi))

    def setGradientStops(self, stops):
        self._gradient.setStops(stops)

    def setMinMaxLabels(self, minTxt, maxTxt):
        self._minLabel.setText(minTxt)
        self._maxLabel.setText(maxTxt)

    def setSuffix(self, suffix):
        self._suffix = suffix
        self._valLabel.setText(str(self._slider.value()) + suffix)

    def setVisible(self, v):
        super().setVisible(v)


# Keep old function for backward compat but unused
def _makeGradientView(gradient, minH=22, maxH=28):
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(gradient))
    view = QGraphicsView(scene)
    view._scene = scene
    view.setFrameShape(QFrame.NoFrame)
    view.setMinimumHeight(minH)
    view.setMaximumHeight(maxH)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return view


class ColorWheel(QWidget):
    """Hue/saturation wheel: angle = hue (0 = red at 3 o'clock, counter-clockwise), distance from centre = saturation.
    Emits colorPicked(hue 0-360, sat 0-100) on click or drag."""
    colorPicked = customSignal(int, int)

    def __init__(self, size=170, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip("Click or drag to pick a colour (around = hue, centre to edge = saturation)")
        self._hue, self._sat = 240, 100

    def setHS(self, hue, sat):
        self._hue, self._sat = int(hue) % 361, int(sat)
        self.update()

    def _geom(self):
        r = min(self.width(), self.height()) / 2 - 6
        return self.width() / 2, self.height() / 2, r

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self._geom()
        cone = QConicalGradient(cx, cy, 0)
        for i in range(7):
            cone.setColorAt(i / 6, QColor.fromHsv((i * 60) % 360, 255, 255))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(cone))
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
        rad = QRadialGradient(cx, cy, r)
        rad.setColorAt(0, QColor(255, 255, 255, 255))
        rad.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(rad))
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
        # marker
        a = math.radians(self._hue)
        d = r * self._sat / 100
        mx, my = cx + d * math.cos(a), cy - d * math.sin(a)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), 3)); p.drawEllipse(int(mx - 6), int(my - 6), 12, 12)
        p.setPen(QPen(QColor(255, 255, 255), 1.5)); p.drawEllipse(int(mx - 6), int(my - 6), 12, 12)
        p.end()

    def _pick(self, pos):
        import math
        cx, cy, r = self._geom()
        dx, dy = pos.x() - cx, cy - pos.y()
        hue = int(round(math.degrees(math.atan2(dy, dx)))) % 360
        sat = int(round(min(1.0, math.hypot(dx, dy) / r) * 100))
        self.setHS(hue, sat)
        self.colorPicked.emit(hue, sat)

    def mousePressEvent(self, event):
        self._pick(event.position() if hasattr(event, "position") else event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position() if hasattr(event, "position") else event.pos())


# (name, hue, saturation) for the one-click swatches on the HSI tab
COLOR_SWATCHES = [("Red", 0, 100), ("Orange", 25, 100), ("Amber", 40, 100), ("Yellow", 58, 100),
                  ("Lime", 90, 100), ("Green", 120, 100), ("Cyan", 180, 100), ("Sky", 205, 100),
                  ("Blue", 240, 100), ("Purple", 275, 100), ("Magenta", 300, 100), ("Pink", 330, 70),
                  ("Warm white", 30, 25), ("White", 0, 0), ("Ice", 200, 25)]


def _swatchStyle(hue, sat):
    c = QColor.fromHsv(int(hue) % 360, int(sat * 2.55), 255)
    return ("QPushButton { background-color: %s; border: 1px solid #555; border-radius: 4px; }"
            "QPushButton:hover { border: 2px solid #ddd; }" % c.name())


class ColorPickDialog(QDialog):
    """Small picker: colour wheel, one-click swatches and the system colour dialog. Returns (hue, sat).
    colorChanged fires on every change while picking, so a caller can preview it live."""

    colorChanged = customSignal(int, int)

    def __init__(self, hue=240, sat=100, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick a colour")
        self._hue, self._sat = int(hue), int(sat)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.wheel = ColorWheel()
        self.wheel.setHS(hue, sat)
        self.wheel.colorPicked.connect(self._set)
        row.addWidget(self.wheel, 0, Qt.AlignTop)
        side = QVBoxLayout()
        grid = QGridLayout(); grid.setSpacing(4)
        for i, (name, h, sv) in enumerate(COLOR_SWATCHES):
            b = QPushButton(); b.setFixedSize(30, 30); b.setToolTip(name); b.setStyleSheet(_swatchStyle(h, sv))
            b.clicked.connect(lambda _=False, h=h, sv=sv: (self._set(h, sv), self.accept()))
            grid.addWidget(b, i // 5, i % 5)
        side.addLayout(grid)
        more = QPushButton("More colours\u2026")
        more.clicked.connect(self._system)
        side.addWidget(more, 0, Qt.AlignLeft)
        self.preview = QLabel(); self.preview.setFixedHeight(28)
        side.addWidget(self.preview)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._set(hue, sat)

    def _set(self, hue, sat):
        self._hue, self._sat = int(hue), int(sat)
        self.wheel.setHS(hue, sat)
        c = QColor.fromHsv(self._hue % 360, int(self._sat * 2.55), 255)
        self.preview.setStyleSheet("background-color: %s; border: 1px solid #555; border-radius: 4px;" % c.name())
        self.colorChanged.emit(self._hue, self._sat)

    def _system(self):
        """System colour dialog, live: every change goes through _set (and so colorChanged).
        Cancel goes back to the colour from before it opened."""
        oldHue, oldSat = self._hue, self._sat
        dlg = QColorDialog(QColor.fromHsv(oldHue % 360, int(oldSat * 2.55), 255), self)
        dlg.setWindowTitle("Pick a colour")

        def live(c):
            if c.isValid():
                h = c.hsvHue()
                self._set(h if h >= 0 else self._hue, round(c.hsvSaturation() / 2.55))

        dlg.currentColorChanged.connect(live)
        if dlg.exec():
            live(dlg.selectedColor())
        else:
            self._set(oldHue, oldSat)

    def color(self):
        return self._hue, self._sat


# Palettes for the Sound tab. None = each mode's own built-in colours.
SOUND_PALETTES = [
    ("Auto (built-in colours)", None),
    ("Rainbow", [(0, 100), (30, 100), (58, 100), (120, 100), (180, 100), (240, 100), (275, 100), (320, 100)]),
    ("Club", [(300, 100), (180, 100), (240, 100)]),
    ("Fire", [(0, 100), (18, 100), (35, 100), (52, 100)]),
    ("Ice", [(185, 100), (205, 100), (230, 100), (200, 25)]),
    ("Sunset", [(330, 90), (10, 100), (30, 100), (270, 85)]),
    ("Ocean", [(170, 100), (195, 100), (225, 100), (250, 90)]),
    ("Forest", [(60, 100), (90, 100), (120, 100), (150, 100)]),
    ("Red & blue", [(0, 100), (240, 100)]),
    ("Purple haze", [(260, 100), (290, 100), (320, 90)]),
]
CUSTOM_PALETTE_NAME = "Custom"


class _PaletteChip(QPushButton):
    """A palette colour chip. Click to edit; drag sideways to reorder (the editor does the moving)."""
    DRAG_DISTANCE = 6

    def __init__(self, editor, index):
        super().__init__()
        self._editor, self.index = editor, index
        self._pressX, self._dragging = None, False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressX, self._dragging = self._x(e), False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pressX is not None and (e.buttons() & Qt.LeftButton):
            if not self._dragging and abs(self._x(e) - self._pressX) >= self.DRAG_DISTANCE:
                self._dragging = True
                self.setDown(False)
                self._editor._dragStart(self.index)
            if self._dragging:
                self._editor._dragMove(self.mapTo(self._editor, e.pos()).x())
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        dragged = self._dragging
        self._pressX, self._dragging = None, False
        if dragged:
            self.setDown(False)  # no click after a drag
            self._editor._dragEnd()
            return
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self._editor._showMenu(e.globalPos(), self.index)

    @staticmethod
    def _x(e):
        return int(e.globalPosition().x()) if hasattr(e, "globalPosition") else e.globalPos().x()


class PaletteEditor(QWidget):
    """Preset dropdown plus a row of colour chips. Click a chip to change it, drag to reorder,
    right-click to copy / paste, + / - to add or remove. Emits changed() whenever the palette changes."""
    changed = customSignal()
    MAX_COLOURS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)
        self.presetCombo = QComboBox()
        for name, _ in SOUND_PALETTES:
            self.presetCombo.addItem(name)
        self.presetCombo.addItem(CUSTOM_PALETTE_NAME)
        self.presetCombo.setToolTip("Colours the sound modes use. Auto keeps each mode's own colours.")
        lay.addWidget(self.presetCombo)
        self.chipRow = QHBoxLayout(); self.chipRow.setSpacing(4)
        lay.addLayout(self.chipRow)
        self.addButton = QPushButton("+"); self.addButton.setFixedWidth(30)
        self.addButton.setToolTip("Add a colour")
        self.removeButton = QPushButton("\u2212"); self.removeButton.setFixedWidth(30)
        self.removeButton.setToolTip("Remove the last colour")
        for b in (self.addButton, self.removeButton):
            b.setObjectName("paletteStepBtn")  # theme: narrow padding so the symbol fits
        lay.addWidget(self.addButton); lay.addWidget(self.removeButton)
        lay.addStretch(1)
        self._colours = None
        self._custom = [(300, 100), (180, 100), (240, 100)]
        self._chips = []
        self.presetCombo.currentIndexChanged.connect(self._presetChosen)
        self.addButton.clicked.connect(self._add)
        self.removeButton.clicked.connect(self._remove)
        self._rebuild()

    def palette(self):
        return list(self._colours) if self._colours else None

    def presetName(self):
        return self.presetCombo.currentText()

    def setPalette(self, presetName, colours=None):
        """Restore a saved palette. Custom needs colours; presets load their own."""
        if presetName == CUSTOM_PALETTE_NAME and colours:
            self._custom = [(int(h), int(sv)) for h, sv in colours][:self.MAX_COLOURS]
        pos = self.presetCombo.findText(presetName)
        if pos >= 0:
            if pos == self.presetCombo.currentIndex():
                self._presetChosen(pos)
            else:
                self.presetCombo.setCurrentIndex(pos)

    def _presetChosen(self, i):
        name = self.presetCombo.itemText(i)
        if name == CUSTOM_PALETTE_NAME:
            self._colours = list(self._custom)
        else:
            cols = dict(SOUND_PALETTES).get(name)
            self._colours = list(cols) if cols else None
        self._rebuild()
        self.changed.emit()

    def _edited(self):
        """A chip was changed: the palette is now Custom."""
        self._custom = list(self._colours)
        self.presetCombo.blockSignals(True)
        self.presetCombo.setCurrentIndex(self.presetCombo.findText(CUSTOM_PALETTE_NAME))
        self.presetCombo.blockSignals(False)
        self._rebuild()
        self.changed.emit()

    def _rebuild(self):
        for c in self._chips:
            self.chipRow.removeWidget(c); c.hide(); c.deleteLater()
        self._chips = []
        cols = self._colours or []
        for i in range(len(cols)):
            b = _PaletteChip(self, i); b.setFixedSize(30, 26)
            b.clicked.connect(lambda _=False, i=i: self._editChip(i))
            self.chipRow.addWidget(b)
            self._chips.append(b)
        self._dragIndex = None
        self._styleChips()
        self.addButton.setEnabled(len(cols) < self.MAX_COLOURS)
        self.removeButton.setEnabled(len(cols) > 1)

    def _styleChips(self):
        for i, (b, (h, sv)) in enumerate(zip(self._chips, self._colours or [])):
            style = _swatchStyle(h, sv)
            if i == self._dragIndex:
                style += "QPushButton { border: 2px solid #fff; }"
            b.setStyleSheet(style)
            b.setToolTip("Colour %d: hue %d\u00BA, saturation %d%%.\nClick to change, drag to reorder, right-click to insert / delete / copy / paste."
                         % (i + 1, h, sv))

    # Drag to reorder: the colour moves live to the slot under the cursor; chips stay put, only restyled.
    def _dragStart(self, i):
        self._dragIndex = i
        self._dragOriginal = list(self._colours)
        self._styleChips()

    def _dragMove(self, x):
        if self._dragIndex is None or not self._chips:
            return
        target = len(self._chips) - 1
        for i, b in enumerate(self._chips):
            if x < b.geometry().center().x() + b.width() // 2:
                target = i
                break
        if target != self._dragIndex:
            self._colours.insert(target, self._colours.pop(self._dragIndex))
            self._dragIndex = target
            self._styleChips()

    # Copy / paste through the system clipboard as hex colours ("#ff00ff, #00ffff").
    @staticmethod
    def _toHex(colours):
        return ", ".join(QColor.fromHsvF((h % 360) / 360.0, sv / 100.0, 1.0).name() for h, sv in colours)

    @staticmethod
    def _fromClipboard():
        """Colours on the clipboard as [(hue, sat)], or [] if there are none."""
        out = []
        for tok in re.split(r"[\s,;]+", QGuiApplication.clipboard().text().strip()):
            if tok and not tok.startswith("#") and re.fullmatch(r"[0-9a-fA-F]{6}", tok):
                tok = "#" + tok
            c = QColor(tok) if tok else QColor()
            if c.isValid():
                out.append((max(c.hsvHue(), 0), round(c.hsvSaturation() / 2.55)))
        return out

    def contextMenuEvent(self, e):
        """Right-click on the editor's empty space: palette actions only (chips call _showMenu themselves)."""
        self._showMenu(e.globalPos(), None)

    def _showMenu(self, globalPos, i):
        menu = self._buildMenu(i)
        menu.exec(globalPos) if hasattr(menu, "exec") else menu.exec_(globalPos)

    def _buildMenu(self, i):
        """Context menu for chip i, or palette-only when i is None."""
        pasted = self._fromClipboard()
        menu = QMenu(self)
        if i is not None:
            a = menu.addAction("Insert colour here…", lambda: self._insert(i))
            a.setEnabled(len(self._colours) < self.MAX_COLOURS)
            a = menu.addAction("Delete colour", lambda: self._delete(i))
            a.setEnabled(len(self._colours) > 1)
            menu.addSeparator()
            menu.addAction("Copy colour", lambda: QGuiApplication.clipboard().setText(self._toHex([self._colours[i]])))
            a = menu.addAction("Paste colour", lambda: self._paste(pasted, i, replace=True))
            a.setEnabled(bool(pasted))
            a = menu.addAction("Paste after", lambda: self._paste(pasted, i + 1))
            a.setEnabled(bool(pasted) and len(self._colours) < self.MAX_COLOURS)
            menu.addSeparator()
        a = menu.addAction("Copy palette", lambda: QGuiApplication.clipboard().setText(self._toHex(self._colours)))
        a.setEnabled(bool(self._colours))
        a = menu.addAction("Paste palette", lambda: self._paste(pasted, 0, replace=True, whole=True))
        a.setEnabled(bool(pasted))
        return menu

    def _delete(self, at):
        if len(self._colours) > 1:
            del self._colours[at]
            self._edited()

    def _livePick(self, start, put):
        """Open the picker and apply each colour to the palette as it is picked, so a running Sound
        engine sends it to the lights straight away. put(colours, colour) returns the new list.
        OK keeps it (the palette becomes Custom); Cancel puts the palette back as it was."""
        before = None if self._colours is None else list(self._colours)
        base = list(self._colours or [])
        dlg = ColorPickDialog(*start, parent=self)

        def show(h, sv):
            new = put(list(base), (int(h), int(sv)))[:self.MAX_COLOURS]
            resized = len(new) != len(self._chips)
            self._colours = new
            self._rebuild() if resized else self._styleChips()
            self.changed.emit()

        dlg.colorChanged.connect(show)
        if dlg.exec():
            show(*dlg.color())
            self._edited()
        else:
            self._colours = before
            self._rebuild()
            self.changed.emit()

    def _insert(self, at):
        """Pick a new colour and put it at slot `at`; that chip and the ones after it move right."""
        self._livePick(self._colours[at], lambda cols, c: cols[:at] + [c] + cols[at:])

    def _paste(self, pasted, at, replace=False, whole=False):
        cols = list(self._colours or [])
        if whole:
            cols = pasted
        elif replace:
            cols[at:at + 1] = pasted
        else:
            cols[at:at] = pasted
        self._colours = cols[:self.MAX_COLOURS]
        self._edited()

    def _dragEnd(self):
        self._dragIndex = None
        if self._colours != self._dragOriginal:
            self._edited()  # becomes Custom
        else:
            self._styleChips()

    def _editChip(self, i):
        self._livePick(self._colours[i], lambda cols, c: cols[:i] + [c] + cols[i + 1:])

    def _add(self):
        start = self._colours[-1] if self._colours else (0, 100)  # from Auto this starts a custom palette
        self._livePick(start, lambda cols, c: cols + [c])

    def _remove(self):
        if self._colours and len(self._colours) > 1:
            self._colours.pop()
            self._edited()


def _addSliderRow(grid, row_offset, label_text, slider, value_label, min_label, max_label, gradient_bar, bold_font=None):
    """Add a slider group (gradient + slider + min/max) to a QGridLayout at row_offset.
    Uses 3 grid rows per slider: gradient row, slider row, min/max row.
    Column 0 = label, Column 1 = gradient/slider/minmax, Column 2 = value.
    All sliders on the same grid share column widths, so everything aligns."""

    # Row 0: label | gradient | value
    lbl = QLabel(label_text)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if bold_font:
        lbl.setFont(bold_font)
    grid.addWidget(lbl, row_offset, 0)
    grid.addWidget(gradient_bar, row_offset, 1)
    value_label.setMinimumWidth(55)
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if bold_font:
        value_label.setFont(bold_font)
    grid.addWidget(value_label, row_offset, 2)

    # Row 1: (empty) | slider | (empty)
    slider.setMinimumHeight(18)
    slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    grid.addWidget(slider, row_offset + 1, 1)

    # Row 2: (empty) | min ... max | (empty)
    minmaxRow = QHBoxLayout()
    minmaxRow.setContentsMargins(0, 0, 0, 0)
    min_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    max_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
    minmaxRow.addWidget(min_label)
    minmaxRow.addStretch(1)
    minmaxRow.addWidget(max_label)
    grid.addLayout(minmaxRow, row_offset + 2, 1)

    return row_offset + 3  # next available row


# === MAIN UI CLASS ===

class Ui_MainWindow(object):

    # --- HSI quick colour picking ---
    def _setHSIColor(self, hue, sat):
        """Move the Hue and Saturation sliders (which drive the lights) to a picked colour."""
        self.Slider_HSI_1_H.setValue(int(hue))
        self.Slider_HSI_2_S.setValue(int(sat))

    def _syncHSIWheel(self, *args):
        self.HSI_ColorWheel.setHS(self.Slider_HSI_1_H.value(), self.Slider_HSI_2_S.value())

    def _openHSIColorDialog(self):
        """System colour dialog that moves the sliders (and so the lights) live as you pick.
        Cancel puts the colour back to what it was."""
        oldHue, oldSat = self.Slider_HSI_1_H.value(), self.Slider_HSI_2_S.value()
        start = QColor.fromHsv(oldHue % 360, int(oldSat * 2.55), 255)
        dlg = QColorDialog(start, self.HSI)
        dlg.setWindowTitle("Pick a light colour")

        def live(c):
            if c.isValid():
                h = c.hsvHue()
                self._setHSIColor(h if h >= 0 else self.Slider_HSI_1_H.value(), round(c.hsvSaturation() / 2.55))

        dlg.currentColorChanged.connect(live)
        if dlg.exec():
            live(dlg.selectedColor())
        else:
            self._setHSIColor(oldHue, oldSat)

    def setupUi(self, MainWindow):
        mainFont = QFont()
        mainFont.setBold(True)
        smallFont = QFont()
        smallFont.setPointSize(8)

        # Gradients
        # Gradient stops for GradientBar widgets
        stops_Bri = [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))]

        stops_RGB = [(0.0, QColor(255,0,0)), (0.16, QColor(255,255,0)), (0.33, QColor(0,255,0)),
                     (0.49, QColor(0,255,255)), (0.66, QColor(0,0,255)), (0.83, QColor(255,0,255)), (1.0, QColor(255,0,0))]

        stops_Sat = [(0.0, QColor(255, 255, 255)), (1.0, QColor(255, 0, 0))]

        stops_CCT = [(0.0, QColor(255, 147, 41)), (1.0, QColor(201, 226, 255))]

        # === WINDOW ===
        MainWindow.setMinimumSize(780, 620)
        MainWindow.resize(900, 800)
        MainWindow.setWindowTitle("NeewerLux")

        self.centralwidget = QWidget(MainWindow)
        MainWindow.setCentralWidget(self.centralwidget)
        mainLayout = QVBoxLayout(self.centralwidget)
        mainLayout.setContentsMargins(6, 6, 6, 2)
        mainLayout.setSpacing(4)

        # === TOOLBAR ===
        toolbarWidget = QWidget()
        toolbarWidget.setObjectName("toolbarWidget")
        toolbar = QHBoxLayout(toolbarWidget)
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)

        self.turnOffButton = QPushButton("Turn Light(s) Off")
        self.turnOffButton.setEnabled(False)
        toolbar.addWidget(self.turnOffButton)
        self.turnOnButton = QPushButton("Turn Light(s) On")
        self.turnOnButton.setEnabled(False)
        toolbar.addWidget(self.turnOnButton)
        toolbar.addSpacing(10)
        self.scanCommandButton = QPushButton("Scan")
        toolbar.addWidget(self.scanCommandButton)
        self.tryConnectButton = QPushButton("Connect")
        self.tryConnectButton.setEnabled(False)
        toolbar.addWidget(self.tryConnectButton)
        toolbar.addSpacing(6)
        self.selectAllButton = QPushButton("Select All")
        self.selectAllButton.setToolTip("Select all lights in the table")
        toolbar.addWidget(self.selectAllButton)

        toolbar.addStretch(1)

        self.httpToggleBtn = QPushButton("HTTP: OFF")
        self.httpToggleBtn.setObjectName("httpToggleBtn")
        self.httpToggleBtn.setProperty("httpActive", False)
        self.httpToggleBtn.setMinimumWidth(100)
        self.httpToggleBtn.setToolTip("Start/stop the HTTP control server")
        toolbar.addWidget(self.httpToggleBtn)
        self.httpOpenWebUIBtn = QPushButton("WebUI")
        self.httpOpenWebUIBtn.setToolTip("Open the web dashboard in your browser")
        self.httpOpenWebUIBtn.setEnabled(False)
        toolbar.addWidget(self.httpOpenWebUIBtn)

        self.fontSmallerBtn = QPushButton("A\u2212")
        self.fontSmallerBtn.setToolTip("Smaller text (Ctrl/Cmd -)")
        self.fontLargerBtn = QPushButton("A+")
        self.fontLargerBtn.setToolTip("Larger text (Ctrl/Cmd +, Ctrl/Cmd 0 to reset)")
        for b in (self.fontSmallerBtn, self.fontLargerBtn):
            b.setObjectName("fontSizeBtn")
            toolbar.addWidget(b)

        self.themeToggleBtn = QPushButton("\u263E")
        self.themeToggleBtn.setObjectName("themeToggleBtn")
        self.themeToggleBtn.setFixedWidth(34)
        self.themeToggleBtn.setToolTip("Toggle dark/light theme")
        toolbar.addWidget(self.themeToggleBtn)

        mainLayout.addWidget(toolbarWidget)

        # === SPLITTER ===
        self.mainSplitter = QSplitter(Qt.Vertical)
        self.mainSplitter.setChildrenCollapsible(False)

        # --- LIGHT TABLE ---
        self.lightTable = QTableWidget()
        self.lightTable.setColumnCount(4)
        self.lightTable.setHorizontalHeaderLabels(["Light Name", "MAC Address", "Linked", "Status"])
        self.lightTable.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.lightTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lightTable.setAlternatingRowColors(True)
        self.lightTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lightTable.verticalHeader().setStretchLastSection(False)
        hdr = self.lightTable.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.lightTable.setMinimumHeight(80)
        self.mainSplitter.addWidget(self.lightTable)

        # --- BOTTOM PANEL (tabs only) ---
        bottomPanel = QWidget()
        bottomLay = QVBoxLayout(bottomPanel)
        bottomLay.setContentsMargins(0, 0, 0, 0)
        bottomLay.setSpacing(4)

        # === PRESETS (own splitter section, resizable) ===
        self.presetScrollArea = QScrollArea()
        self.presetScrollArea.setWidgetResizable(True)
        self.presetScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.presetScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.presetScrollArea.setFrameShape(QFrame.NoFrame)
        self.presetScrollArea.setMinimumHeight(68)

        self.customPresetButtonsCW = QWidget()
        # Use a VBox with a grid inside + stretch, so buttons stay top-aligned
        self._presetOuterLay = QVBoxLayout(self.customPresetButtonsCW)
        self._presetOuterLay.setContentsMargins(0, 0, 0, 0)
        self._presetOuterLay.setSpacing(0)
        self.customPresetButtonsLay = QGridLayout()
        self.customPresetButtonsLay.setContentsMargins(0, 0, 0, 0)
        self.customPresetButtonsLay.setSpacing(3)
        for c in range(8):
            self.customPresetButtonsLay.setColumnStretch(c, 1)
        self._presetOuterLay.addLayout(self.customPresetButtonsLay)
        self._presetOuterLay.addStretch(1)  # pushes buttons to top
        self.presetScrollArea.setWidget(self.customPresetButtonsCW)

        self.presetButtons = []

        # === TABS ===
        self.ColorModeTabWidget = QTabWidget()
        self.ColorModeTabWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # --- CCT ---
        self.CCT = QWidget()
        cctLay = QVBoxLayout(self.CCT)
        cctLay.setContentsMargins(8, 8, 8, 8)
        cctLay.setSpacing(6)
        cctGrid = QGridLayout()
        cctGrid.setSpacing(2)
        cctGrid.setColumnStretch(1, 1)  # gradient/slider column stretches

        self.Slider_CCT_Hue = QSlider(Qt.Horizontal); self.Slider_CCT_Hue.setRange(32, 56); self.Slider_CCT_Hue.setValue(56)
        self.TFV_CCT_Hue = QLabel("5600K"); self.TFV_CCT_Hue.setFont(mainFont)
        self.TFV_CCT_Hue_Min = QLabel("3200K"); self.TFV_CCT_Hue_Min.setFont(smallFont)
        self.TFV_CCT_Hue_Max = QLabel("5600K"); self.TFV_CCT_Hue_Max.setFont(smallFont)
        self.TFL_CCT_Hue = QLabel("Color Temp")
        self.CCT_Temp_Gradient_BG = _makeGradientBar(stops_CCT)
        row = _addSliderRow(cctGrid, 0, "Color Temp:", self.Slider_CCT_Hue, self.TFV_CCT_Hue,
                            self.TFV_CCT_Hue_Min, self.TFV_CCT_Hue_Max, self.CCT_Temp_Gradient_BG, mainFont)

        self.Slider_CCT_Bright = QSlider(Qt.Horizontal); self.Slider_CCT_Bright.setRange(0, 100); self.Slider_CCT_Bright.setValue(100)
        self.TFV_CCT_Bright = QLabel("100%"); self.TFV_CCT_Bright.setFont(mainFont)
        self.TFV_CCT_Bright_Max = QLabel("100"); self.TFV_CCT_Bright_Max.setFont(smallFont)
        self.TFV_CCT_Bright_Min = QLabel("0"); self.TFV_CCT_Bright_Min.setFont(smallFont)
        self.TFL_CCT_Bright = QLabel("Brightness")
        self.CCT_Bright_Gradient_BG = _makeGradientBar(stops_Bri)
        row = _addSliderRow(cctGrid, row, "Brightness:", self.Slider_CCT_Bright, self.TFV_CCT_Bright,
                            self.TFV_CCT_Bright_Min, self.TFV_CCT_Bright_Max, self.CCT_Bright_Gradient_BG, mainFont)
        cctLay.addLayout(cctGrid)
        cctLay.addStretch(1)
        self.ColorModeTabWidget.addTab(self.CCT, "CCT")

        # --- HSI ---
        self.HSI = QWidget()
        hsiLay = QVBoxLayout(self.HSI)
        hsiLay.setContentsMargins(8, 8, 8, 8)
        hsiLay.setSpacing(6)
        hsiGrid = QGridLayout()
        hsiGrid.setSpacing(2)
        hsiGrid.setColumnStretch(1, 1)

        self.Slider_HSI_1_H = QSlider(Qt.Horizontal); self.Slider_HSI_1_H.setRange(0, 360); self.Slider_HSI_1_H.setValue(240)
        self.TFV_HSI_1_H = QLabel("240\u00BA"); self.TFV_HSI_1_H.setFont(mainFont)
        self.TFV_HSI_1_H_Min = QLabel("0"); self.TFV_HSI_1_H_Min.setFont(smallFont)
        self.TFV_HSI_1_H_Max = QLabel("360"); self.TFV_HSI_1_H_Max.setFont(smallFont)
        self.TFL_HSI_1_H = QLabel("Hue")
        self.HSI_Hue_Gradient_BG = _makeGradientBar(stops_RGB)
        row = _addSliderRow(hsiGrid, 0, "Hue:", self.Slider_HSI_1_H, self.TFV_HSI_1_H,
                            self.TFV_HSI_1_H_Min, self.TFV_HSI_1_H_Max, self.HSI_Hue_Gradient_BG, mainFont)

        self.Slider_HSI_2_S = QSlider(Qt.Horizontal); self.Slider_HSI_2_S.setRange(0, 100); self.Slider_HSI_2_S.setValue(100)
        self.TFV_HSI_2_S = QLabel("100%"); self.TFV_HSI_2_S.setFont(mainFont)
        self.TFV_HSI_2_S_Min = QLabel("0"); self.TFV_HSI_2_S_Min.setFont(smallFont)
        self.TFV_HSI_2_S_Max = QLabel("100"); self.TFV_HSI_2_S_Max.setFont(smallFont)
        self.TFL_HSI_2_S = QLabel("Saturation")
        self.HSI_Sat_Gradient_BG = _makeGradientBar(stops_Sat)
        row = _addSliderRow(hsiGrid, row, "Saturation:", self.Slider_HSI_2_S, self.TFV_HSI_2_S,
                            self.TFV_HSI_2_S_Min, self.TFV_HSI_2_S_Max, self.HSI_Sat_Gradient_BG, mainFont)

        self.Slider_HSI_3_L = QSlider(Qt.Horizontal); self.Slider_HSI_3_L.setRange(0, 100); self.Slider_HSI_3_L.setValue(100)
        self.TFV_HSI_3_L = QLabel("100%"); self.TFV_HSI_3_L.setFont(mainFont)
        self.TFV_HSI_3_L_Min = QLabel("0"); self.TFV_HSI_3_L_Min.setFont(smallFont)
        self.TFV_HSI_3_L_Max = QLabel("100"); self.TFV_HSI_3_L_Max.setFont(smallFont)
        self.TFL_HSI_3_L = QLabel("Intensity")
        self.HSI_Int_Gradient_BG = _makeGradientBar(stops_Bri)
        row = _addSliderRow(hsiGrid, row, "Intensity:", self.Slider_HSI_3_L, self.TFV_HSI_3_L,
                            self.TFV_HSI_3_L_Min, self.TFV_HSI_3_L_Max, self.HSI_Int_Gradient_BG, mainFont)
        hsiLay.addLayout(hsiGrid)

        # Quick colour picking: wheel + swatches + system picker. They only move the sliders above,
        # so sending to the lights goes through the existing slider wiring.
        pickRow = QHBoxLayout()
        self.HSI_ColorWheel = ColorWheel()
        pickRow.addWidget(self.HSI_ColorWheel, 0, Qt.AlignTop)
        swatchBox = QVBoxLayout()
        swatchGrid = QGridLayout(); swatchGrid.setSpacing(4)
        for i, (name, h, sat) in enumerate(COLOR_SWATCHES):
            b = QPushButton(); b.setFixedSize(32, 32); b.setToolTip(name)
            b.setStyleSheet(_swatchStyle(h, sat))
            b.clicked.connect(lambda _=False, h=h, sat=sat: self._setHSIColor(h, sat))
            swatchGrid.addWidget(b, i // 5, i % 5)
        swatchBox.addLayout(swatchGrid)
        self.HSI_MoreColors = QPushButton("More colours\u2026")
        self.HSI_MoreColors.setToolTip("Open the system colour picker (eyedropper, hex codes, saved colours)")
        self.HSI_MoreColors.clicked.connect(self._openHSIColorDialog)
        swatchBox.addWidget(self.HSI_MoreColors, 0, Qt.AlignLeft)
        swatchBox.addStretch(1)
        pickRow.addLayout(swatchBox)
        pickRow.addStretch(1)
        hsiLay.addLayout(pickRow)

        self.HSI_ColorWheel.colorPicked.connect(self._setHSIColor)
        self.Slider_HSI_1_H.valueChanged.connect(self._syncHSIWheel)
        self.Slider_HSI_2_S.valueChanged.connect(self._syncHSIWheel)
        self._syncHSIWheel()
        hsiLay.addStretch(1)
        self.ColorModeTabWidget.addTab(self.HSI, "HSI")

        # --- SCENE ---
        self.ANM = QWidget()
        anmLay = QVBoxLayout(self.ANM)
        anmLay.setContentsMargins(8, 8, 8, 8)
        anmLay.setSpacing(6)

        sceneGrid = QGridLayout(); sceneGrid.setSpacing(4)
        self.Button_1_police_A = QPushButton("1 - Police\n(Red/Blue)")
        self.Button_1_police_B = QPushButton("2 - Ambulance\n(Red/White)")
        self.Button_1_police_C = QPushButton("3 - Fire Truck\n(Red/Orange)")
        self.Button_2_party_A = QPushButton("4 - Fireworks\n(Rainbow)")
        self.Button_2_party_B = QPushButton("5 - Party\n(Rainbow)")
        self.Button_2_party_C = QPushButton("6 - Candlelight\n(Warm White)")
        self.Button_3_lightning_A = QPushButton("7 - Lightning\n(White)")
        self.Button_3_lightning_B = QPushButton("8 - Paparazzi\n(White)")
        self.Button_3_lightning_C = QPushButton("9 - TV Screen\n(White)")
        sceneBtns = [self.Button_1_police_A, self.Button_1_police_B, self.Button_1_police_C,
                     self.Button_2_party_A, self.Button_2_party_B, self.Button_2_party_C,
                     self.Button_3_lightning_A, self.Button_3_lightning_B, self.Button_3_lightning_C]
        for btn in sceneBtns:
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        for i, btn in enumerate(sceneBtns):
            sceneGrid.addWidget(btn, i // 3, i % 3)
        anmLay.addLayout(sceneGrid)

        self.Slider_ANM_Brightness = QSlider(Qt.Horizontal); self.Slider_ANM_Brightness.setRange(0, 100); self.Slider_ANM_Brightness.setValue(100)
        self.TFV_ANM_Brightness = QLabel("100%"); self.TFV_ANM_Brightness.setFont(mainFont)
        self.TFV_ANM_Brightness_Min = QLabel("0"); self.TFV_ANM_Brightness_Min.setFont(smallFont)
        self.TFV_ANM_Brightness_Max = QLabel("100"); self.TFV_ANM_Brightness_Max.setFont(smallFont)
        self.TFL_ANM_Brightness = QLabel("Brightness")
        self.ANM_Brightness_Gradient_BG = _makeGradientBar(stops_Bri)
        anmGrid = QGridLayout()
        anmGrid.setSpacing(2)
        anmGrid.setColumnStretch(1, 1)
        _addSliderRow(anmGrid, 0, "Brightness:", self.Slider_ANM_Brightness, self.TFV_ANM_Brightness,
                      self.TFV_ANM_Brightness_Min, self.TFV_ANM_Brightness_Max,
                      self.ANM_Brightness_Gradient_BG, mainFont)
        anmLay.addLayout(anmGrid)
        # Compat labels
        self.TFL_A_policeAnim = QLabel(""); self.TFL_B_partyAnim = QLabel(""); self.TFL_C_lightningAnim = QLabel("")
        anmLay.addStretch(1)
        self.ColorModeTabWidget.addTab(self.ANM, "Scene")

        # --- ANIMATIONS ---
        self.animTab = QWidget()
        animLay = QHBoxLayout(self.animTab)
        animLay.setContentsMargins(8, 8, 8, 8)
        animLay.setSpacing(8)

        self.animList = QListWidget()
        self.animList.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        animLay.addWidget(self.animList, 1)

        animCtrlScroll = QScrollArea()
        animCtrlScroll.setWidgetResizable(True)
        animCtrlScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        animCtrlScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        animCtrlScroll.setFrameShape(QFrame.NoFrame)
        animCtrlWidget = QWidget()
        animCtrl = QVBoxLayout(animCtrlWidget); animCtrl.setSpacing(4); animCtrl.setContentsMargins(0, 0, 4, 0)

        r1 = QHBoxLayout()
        self.animPlayButton = QPushButton("\u25B6 Play")
        self.animStopButton = QPushButton("\u25A0 Stop")
        r1.addWidget(self.animPlayButton); r1.addWidget(self.animStopButton)
        animCtrl.addLayout(r1)
        r2 = QHBoxLayout()
        self.animExportButton = QPushButton("Export JSON")
        self.animImportButton = QPushButton("Import JSON")
        r2.addWidget(self.animExportButton); r2.addWidget(self.animImportButton)
        animCtrl.addLayout(r2)

        # Toggles
        chkRow = QHBoxLayout()
        self.animParallelCheck = QCheckBox("Parallel"); self.animParallelCheck.setChecked(True)
        self.animParallelCheck.setToolTip("Send BLE commands to all lights simultaneously")
        self.animRevertCheck = QCheckBox("Revert on finish"); self.animRevertCheck.setChecked(True)
        self.animRevertCheck.setToolTip("Restore lights to pre-animation state when stopped or finished")
        chkRow.addWidget(self.animParallelCheck); chkRow.addWidget(self.animRevertCheck)
        animCtrl.addLayout(chkRow)

        # Labeled controls grid
        cg = QGridLayout(); cg.setSpacing(4)
        loopL = QLabel("Loop:"); loopL.setFont(mainFont); cg.addWidget(loopL, 0, 0)
        self.animLoopCheck = QCheckBox(); cg.addWidget(self.animLoopCheck, 0, 1)
        loopCountL = QLabel("Loops:"); loopCountL.setFont(mainFont); cg.addWidget(loopCountL, 1, 0)
        self.animLoopCountSpin = SpinBoxWithButtons(minVal=0, maxVal=999, value=0)
        self.animLoopCountSpin.setToolTip("0 = infinite (if Loop checked), N = play N times then stop")
        cg.addWidget(self.animLoopCountSpin, 1, 1)
        spdL = QLabel("Speed:"); spdL.setFont(mainFont); cg.addWidget(spdL, 2, 0)
        self.animSpeedCombo = QComboBox()
        self.animSpeedCombo.setEditable(True)
        self.animSpeedCombo.addItems(["0.25x", "0.5x", "1x", "1.5x", "2x", "3x", "4x"])
        self.animSpeedCombo.setCurrentIndex(2)
        self.animSpeedCombo.setToolTip("Multiplier applied to all animation timing\nType a custom value (e.g. 0.75x)")
        self.animSpeedCombo.setMinimumWidth(90)
        cg.addWidget(self.animSpeedCombo, 2, 1)
        rL = QLabel("Rate:"); rL.setFont(mainFont); cg.addWidget(rL, 3, 0)
        self.animRateSpin = SpinBoxWithButtons(minVal=1, maxVal=30, value=5)
        self.animRateSpin.setToolTip("BLE updates per second during fades.\n"
            "With Parallel OFF: ~5/s max (each light takes ~50ms sequentially)\n"
            "With Parallel ON: ~15/s achievable regardless of light count\n"
            "Higher = smoother fades but more BLE traffic")
        cg.addWidget(self.animRateSpin, 3, 1)
        briL = QLabel("Brightness:"); briL.setFont(mainFont); cg.addWidget(briL, 4, 0)
        self.animBriSpin = SpinBoxWithButtons(minVal=5, maxVal=100, value=100, suffix="%")
        cg.addWidget(self.animBriSpin, 4, 1)
        animCtrl.addLayout(cg)

        self.animStatusLabel = QLabel("Stopped")
        self.animStatusLabel.setAlignment(Qt.AlignCenter)
        self.animStatusLabel.setWordWrap(True)
        animCtrl.addWidget(self.animStatusLabel)
        animCtrl.addStretch(1)

        mgmt = QHBoxLayout()
        self.animNewButton = QPushButton("+New")
        self.animEditButton = QPushButton("Edit")
        self.animDeleteButton = QPushButton("Delete")
        self.animDuplicateButton = QPushButton("Duplicate")
        for b in [self.animNewButton, self.animEditButton, self.animDeleteButton, self.animDuplicateButton]:
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); mgmt.addWidget(b)
        animCtrl.addLayout(mgmt)
        animCtrlScroll.setWidget(animCtrlWidget)
        animLay.addWidget(animCtrlScroll)
        self.ColorModeTabWidget.addTab(self.animTab, "Animations")

        # --- LIGHT PREFS ---
        self.lightPrefs = QWidget()
        lpLay = QVBoxLayout(self.lightPrefs)
        lpLay.setContentsMargins(8, 8, 8, 8)
        lpLay.setSpacing(6)

        nameRow = QHBoxLayout()
        self.customName = QCheckBox("Custom Name for this light:")
        self.customName.setFont(mainFont)
        nameRow.addWidget(self.customName, 1)
        nameRow.addWidget(QLabel("Preferred ID:"))
        self.preferredIDSpin = QSpinBox(); self.preferredIDSpin.setRange(0, 99); self.preferredIDSpin.setMinimumWidth(65)
        self.preferredIDSpin.setToolTip("Fixed numeric ID (0 = auto)")
        nameRow.addWidget(self.preferredIDSpin)
        lpLay.addLayout(nameRow)

        self.customNameTF = QLineEdit(); self.customNameTF.setMaxLength(80)
        self.customNameTF.setPlaceholderText("Enter a custom name...")
        lpLay.addWidget(self.customNameTF)
        lpLay.addSpacing(10)

        self.colorTempRange = QCheckBox("Use Custom Color Temperature Range for CCT mode:")
        self.colorTempRange.setFont(mainFont)
        lpLay.addWidget(self.colorTempRange)
        tempRow = QHBoxLayout()
        self.colorTempRange_Min_TF = QLineEdit(); self.colorTempRange_Min_TF.setMaxLength(10); self.colorTempRange_Min_TF.setPlaceholderText("Min")
        self.colorTempRange_Max_TF = QLineEdit(); self.colorTempRange_Max_TF.setMaxLength(10); self.colorTempRange_Max_TF.setPlaceholderText("Max")
        tempRow.addWidget(self.colorTempRange_Min_TF); tempRow.addWidget(QLabel("to")); tempRow.addWidget(self.colorTempRange_Max_TF); tempRow.addStretch(1)
        lpLay.addLayout(tempRow)
        lpLay.addSpacing(10)

        self.onlyCCTModeCheck = QCheckBox("This light can only use CCT mode\n(for Neewer lights without HSI mode)")
        self.onlyCCTModeCheck.setFont(mainFont)
        lpLay.addWidget(self.onlyCCTModeCheck)
        lpLay.addStretch(1)
        self.saveLightPrefsButton = QPushButton("Save Preferences")
        lpLay.addWidget(self.saveLightPrefsButton, alignment=Qt.AlignRight)
        self.ColorModeTabWidget.addTab(self.lightPrefs, "Light Preferences")

        # --- GLOBAL PREFS ---
        self.globalPrefs = QScrollArea()
        self.globalPrefsCW = QWidget()
        self.globalPrefsLay = QFormLayout(self.globalPrefsCW)
        self.globalPrefsLay.setLabelAlignment(Qt.AlignLeft)
        self.globalPrefs.setWidget(self.globalPrefsCW)
        self.globalPrefs.setWidgetResizable(True)

        self.findLightsOnStartup_check = QCheckBox("Scan for Neewer lights on program launch")
        self.autoConnectToLights_check = QCheckBox("Automatically try to link to newly found lights")
        self.printDebug_check = QCheckBox("Print debug information to the console")
        self.rememberLightsOnExit_check = QCheckBox("Remember the last mode parameters set for lights on exit")
        self.rememberPresetsOnExit_check = QCheckBox("Save configuration of custom presets on exit")
        self.livePreview_check = QCheckBox("Live Preview (send settings in real-time as sliders move)")
        self.livePreview_check.setChecked(True)
        self.autoReconnect_check = QCheckBox("Automatically reconnect after disconnection")
        self.hideConsoleOnLaunch_check = QCheckBox("Hide console on startup (only when launched via python.exe)")
        self.minimizeToTrayOnClose_check = QCheckBox("Minimize to system tray on close (uncheck to quit on close)")
        self.minimizeToTrayOnClose_check.setChecked(True)
        self.httpAutoStart_check = QCheckBox("Start HTTP server automatically on launch")
        self.httpPortField = QLineEdit("8080")
        self.httpPortField.setFixedWidth(70)
        self.httpPortField.setToolTip("Port for the HTTP server (1024-65535, default 8080). Restart the server to apply.")
        cctFallbackRow = QHBoxLayout()
        cctFallbackLabel = QLabel("Incompatible command handling:")
        self.cctFallbackCombo = QComboBox()
        self.cctFallbackCombo.addItems(["Convert / Clamp (adapt to light capabilities)", "Ignore / Skip (discard incompatible commands)"])
        self.cctFallbackCombo.setToolTip("How to handle commands a light can't execute:\n"
            "- HSI/Scene sent to a CCT-only light\n"
            "- Color temperature outside a light's supported range\n\n"
            "Convert/Clamp: adapt the command (map HSI to CCT, clamp temp to range)\n"
            "Ignore/Skip: silently drop the command for that light")
        cctFallbackRow.addWidget(cctFallbackLabel)
        cctFallbackRow.addWidget(self.cctFallbackCombo, 1)
        cctRangeRow = QHBoxLayout()
        cctRangeLabel = QLabel("Global CCT range:")
        self.globalCCTMinSpin = QSpinBox()
        self.globalCCTMinSpin.setRange(2700, 8500); self.globalCCTMinSpin.setValue(3200)
        self.globalCCTMinSpin.setSuffix("K"); self.globalCCTMinSpin.setSingleStep(100)
        self.globalCCTMinSpin.setButtonSymbols(QSpinBox.NoButtons)
        self.globalCCTMaxSpin = QSpinBox()
        self.globalCCTMaxSpin.setRange(2700, 8500); self.globalCCTMaxSpin.setValue(5600)
        self.globalCCTMaxSpin.setSuffix("K"); self.globalCCTMaxSpin.setSingleStep(100)
        self.globalCCTMaxSpin.setButtonSymbols(QSpinBox.NoButtons)
        cctRangeRow.addWidget(cctRangeLabel)
        cctRangeRow.addWidget(self.globalCCTMinSpin)
        cctRangeRow.addWidget(QLabel("to"))
        cctRangeRow.addWidget(self.globalCCTMaxSpin)
        self.maxNumOfAttempts_field = QLineEdit(); self.maxNumOfAttempts_field.setFixedWidth(50)
        self.acceptable_HTTP_IPs_field = QTextEdit(); self.acceptable_HTTP_IPs_field.setFixedHeight(70)
        self.whiteListedMACs_field = QTextEdit(); self.whiteListedMACs_field.setFixedHeight(70)

        self.resetGlobalPrefsButton = QPushButton("Reset Preferences to Defaults")
        self.saveGlobalPrefsButton = QPushButton("Save Global Preferences")

        # Keyboard shortcut sections
        self.windowButtonsCW = QWidget(); self.windowButtonsLay = QGridLayout(self.windowButtonsCW)
        self.SC_turnOffButton_field = singleKeySequenceEditCancel("Ctrl+PgDown")
        self.windowButtonsLay.addWidget(QLabel("Turn Off", alignment=Qt.AlignCenter), 1, 1)
        self.windowButtonsLay.addWidget(self.SC_turnOffButton_field, 2, 1)
        self.SC_turnOnButton_field = singleKeySequenceEditCancel("Ctrl+PgUp")
        self.windowButtonsLay.addWidget(QLabel("Turn On", alignment=Qt.AlignCenter), 1, 2)
        self.windowButtonsLay.addWidget(self.SC_turnOnButton_field, 2, 2)
        self.SC_scanCommandButton_field = singleKeySequenceEditCancel("Ctrl+Shift+S")
        self.windowButtonsLay.addWidget(QLabel("Scan", alignment=Qt.AlignCenter), 1, 3)
        self.windowButtonsLay.addWidget(self.SC_scanCommandButton_field, 2, 3)
        self.SC_tryConnectButton_field = singleKeySequenceEditCancel("Ctrl+Shift+C")
        self.windowButtonsLay.addWidget(QLabel("Connect", alignment=Qt.AlignCenter), 1, 4)
        self.windowButtonsLay.addWidget(self.SC_tryConnectButton_field, 2, 4)

        self.tabSwitchCW = QWidget(); self.tabSwitchLay = QGridLayout(self.tabSwitchCW)
        self.SC_Tab_CCT_field = singleKeySequenceEditCancel("Alt+1")
        self.tabSwitchLay.addWidget(QLabel("CCT", alignment=Qt.AlignCenter), 1, 1)
        self.tabSwitchLay.addWidget(self.SC_Tab_CCT_field, 2, 1)
        self.SC_Tab_HSI_field = singleKeySequenceEditCancel("Alt+2")
        self.tabSwitchLay.addWidget(QLabel("HSI", alignment=Qt.AlignCenter), 1, 2)
        self.tabSwitchLay.addWidget(self.SC_Tab_HSI_field, 2, 2)
        self.SC_Tab_SCENE_field = singleKeySequenceEditCancel("Alt+3")
        self.tabSwitchLay.addWidget(QLabel("Scene", alignment=Qt.AlignCenter), 1, 3)
        self.tabSwitchLay.addWidget(self.SC_Tab_SCENE_field, 2, 3)
        self.SC_Tab_PREFS_field = singleKeySequenceEditCancel("Alt+4")
        self.tabSwitchLay.addWidget(QLabel("Prefs", alignment=Qt.AlignCenter), 1, 4)
        self.tabSwitchLay.addWidget(self.SC_Tab_PREFS_field, 2, 4)

        self.brightnessCW = QWidget(); self.brightnessLay = QGridLayout(self.brightnessCW)
        self.SC_Dec_Bri_Small_field = singleKeySequenceEditCancel("/")
        self.brightnessLay.addWidget(QLabel("Bri -", alignment=Qt.AlignCenter), 1, 1)
        self.brightnessLay.addWidget(self.SC_Dec_Bri_Small_field, 2, 1)
        self.SC_Dec_Bri_Large_field = singleKeySequenceEditCancel("Ctrl+/")
        self.brightnessLay.addWidget(QLabel("Bri --", alignment=Qt.AlignCenter), 1, 2)
        self.brightnessLay.addWidget(self.SC_Dec_Bri_Large_field, 2, 2)
        self.SC_Inc_Bri_Small_field = singleKeySequenceEditCancel("*")
        self.brightnessLay.addWidget(QLabel("Bri +", alignment=Qt.AlignCenter), 1, 3)
        self.brightnessLay.addWidget(self.SC_Inc_Bri_Small_field, 2, 3)
        self.SC_Inc_Bri_Large_field = singleKeySequenceEditCancel("Ctrl+*")
        self.brightnessLay.addWidget(QLabel("Bri ++", alignment=Qt.AlignCenter), 1, 4)
        self.brightnessLay.addWidget(self.SC_Inc_Bri_Large_field, 2, 4)

        self.sliderAdjustmentCW = QWidget(); self.sliderAdjustmentLay = QGridLayout(self.sliderAdjustmentCW)
        _defaults = [("7","Ctrl+7","9","Ctrl+9"), ("4","Ctrl+4","6","Ctrl+6"), ("1","Ctrl+1","3","Ctrl+3")]
        for ri, (ds, dl, Is, Il) in enumerate(_defaults):
            rb = ri * 2
            n = str(ri + 1)
            dec_s = singleKeySequenceEditCancel(ds); dec_l = singleKeySequenceEditCancel(dl)
            inc_s = singleKeySequenceEditCancel(Is); inc_l = singleKeySequenceEditCancel(Il)
            setattr(self, f"SC_Dec_{n}_Small_field", dec_s)
            setattr(self, f"SC_Dec_{n}_Large_field", dec_l)
            setattr(self, f"SC_Inc_{n}_Small_field", inc_s)
            setattr(self, f"SC_Inc_{n}_Large_field", inc_l)
            self.sliderAdjustmentLay.addWidget(QLabel(f"S{n} -", alignment=Qt.AlignCenter), rb+1, 1)
            self.sliderAdjustmentLay.addWidget(dec_s, rb+2, 1)
            self.sliderAdjustmentLay.addWidget(QLabel(f"S{n} --", alignment=Qt.AlignCenter), rb+1, 2)
            self.sliderAdjustmentLay.addWidget(dec_l, rb+2, 2)
            self.sliderAdjustmentLay.addWidget(QLabel(f"S{n} +", alignment=Qt.AlignCenter), rb+1, 3)
            self.sliderAdjustmentLay.addWidget(inc_s, rb+2, 3)
            self.sliderAdjustmentLay.addWidget(QLabel(f"S{n} ++", alignment=Qt.AlignCenter), rb+1, 4)
            self.sliderAdjustmentLay.addWidget(inc_l, rb+2, 4)

        self.bottomButtonsCW = QWidget(); self.bottomButtonsLay = QGridLayout(self.bottomButtonsCW)
        self.bottomButtonsLay.addWidget(self.resetGlobalPrefsButton, 1, 1)
        self.bottomButtonsLay.addWidget(self.saveGlobalPrefsButton, 1, 2)

        # Build form, organized into logical sections
        self.globalPrefsLay.addRow(QLabel("<strong>Startup &amp; Connection</strong>"))
        self.globalPrefsLay.addRow(self.findLightsOnStartup_check)
        self.globalPrefsLay.addRow(self.autoConnectToLights_check)
        self.globalPrefsLay.addRow(self.autoReconnect_check)
        self.globalPrefsLay.addRow("Max connection retries:", self.maxNumOfAttempts_field)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Control &amp; Presets</strong>"))
        self.globalPrefsLay.addRow(self.livePreview_check)
        self.globalPrefsLay.addRow(self.rememberLightsOnExit_check)
        self.globalPrefsLay.addRow(self.rememberPresetsOnExit_check)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Light Behaviour</strong>"))
        self.globalPrefsLay.addRow(cctFallbackRow)
        self.globalPrefsLay.addRow(cctRangeRow)

        self.globalPrefsLay.addRow(QLabel("<br><strong>HTTP Server</strong>"))
        self.globalPrefsLay.addRow(self.httpAutoStart_check)
        self.globalPrefsLay.addRow("HTTP server port:", self.httpPortField)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Window &amp; Display</strong>"))
        self.globalPrefsLay.addRow(self.hideConsoleOnLaunch_check)
        self.globalPrefsLay.addRow(self.minimizeToTrayOnClose_check)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Logging</strong>"))
        self.enableLogTab_check = QCheckBox("Enable Log tab (show debug output in GUI)")
        self.enableLogTab_check.setChecked(True)
        self.logToFile_check = QCheckBox("Also write log to file (light_prefs/NeewerLux.log)")
        self.logHeartbeat_check = QCheckBox("Log a background heartbeat every 30 seconds")
        self.globalPrefsLay.addRow(self.enableLogTab_check)
        self.globalPrefsLay.addRow(self.logToFile_check)
        self.globalPrefsLay.addRow(self.logHeartbeat_check)
        self.globalPrefsLay.addRow(self.printDebug_check)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Filtering</strong>"))
        self.globalPrefsLay.addRow(QLabel("Acceptable IPs for HTTP Server:"))
        self.globalPrefsLay.addRow(self.acceptable_HTTP_IPs_field)
        self.globalPrefsLay.addRow(QLabel("Whitelisted MAC Addresses:"))
        self.globalPrefsLay.addRow(self.whiteListedMACs_field)

        self.globalPrefsLay.addRow(QLabel("<br><strong>Keyboard Shortcuts</strong>"))
        self.globalPrefsLay.addRow(self.windowButtonsCW)
        self.globalPrefsLay.addRow(self.tabSwitchCW)
        self.globalPrefsLay.addRow(self.brightnessCW)
        self.globalPrefsLay.addRow(self.sliderAdjustmentCW)
        self.globalPrefsLay.addRow(self.bottomButtonsCW)
        self.ColorModeTabWidget.addTab(self.globalPrefs, "Global Preferences")

        # --- INFO TAB ---
        self.infoTab = QWidget()
        infoLay = QVBoxLayout(self.infoTab)
        infoLay.setContentsMargins(10, 10, 10, 10)

        # Update notification banner
        self.updateBanner = QLabel("")
        self.updateBanner.setWordWrap(True)
        self.updateBanner.setOpenExternalLinks(True)
        self.updateBanner.setVisible(False)
        self.updateBanner.setStyleSheet("QLabel { background-color: #1a3a1a; color: #4caf50; padding: 8px; border: 1px solid #4caf50; border-radius: 4px; }")
        infoLay.addWidget(self.updateBanner)

        self.checkUpdateButton = QPushButton("Check for Updates")
        self.checkUpdateButton.setToolTip("Check GitHub for a newer version of NeewerLux")
        infoLay.addWidget(self.checkUpdateButton)

        self.infoText = QTextBrowser()
        self.infoText.setReadOnly(True)
        self.infoText.setOpenExternalLinks(True)
        self.infoText.setHtml("""
<h2>NeewerLux {VERSION}</h2>

<h3>Lights</h3>
<p>Scan for Neewer lights over Bluetooth and control them in CCT, HSI, or Scene mode.
Give a light a name and a fixed number in Light Preferences and it keeps its place in
the table, and can be addressed by that name in animations and HTTP commands.</p>

<h3>Colour temperature limits</h3>
<p>Set the CCT range your lights should stay within, globally or per light. A command
outside a light's range is either converted to the nearest value it can reach or skipped
entirely, depending on which you pick in Global Preferences. Useful when mixing models
with different ranges.</p>

<h3>Presets</h3>
<p>Right-click a preset button to save the current setup, left-click to recall it,
middle-click to rename. A preset can target one light or all of them. The Preset Editor
offers the same thing as a table if you would rather work that way.</p>

<h3>Animations</h3>
<p>101 animations ship with the app, covering emergency, stage, holiday, studio, and
ambient looks. The editor works on keyframes with a table and live preview, or you can
edit the underlying JSON directly. CCT-only lights follow colour animations by mapping
hue to the nearest temperature, so mixed setups stay in step.</p>
<p>Animations target lights by name, by number, by MAC address, or with <code>*</code>
for all of them.</p>

<h3>Remote control</h3>
<p>Turn on the HTTP server to drive everything from a browser or from hardware such as a
Stream Deck. The dashboard lives at <code>http://localhost:8080/</code>, and every action
is also available as a plain URL. The port is configurable in Global Preferences.</p>

<h3>Files</h3>
<p>Presets, animations, and per-light settings are plain files in the
<code>light_prefs</code> folder next to the application. They can be edited by hand and
copied between installations.</p>

<hr>

<h3>HTTP reference</h3>
<p><b>Base URL:</b> <code>http://localhost:8080/NeewerLux/doAction?</code></p>
<table cellpadding="4">
<tr><td><b>discover</b></td><td>Scan for new lights</td></tr>
<tr><td><b>link=N</b></td><td>Connect to light N, or <code>all</code></td></tr>
<tr><td><b>light=N&amp;mode=CCT&amp;temp=5600&amp;bri=100</b></td><td>Set a light to CCT mode</td></tr>
<tr><td><b>light=N&amp;mode=HSI&amp;hue=240&amp;sat=100&amp;bri=80</b></td><td>Set a light to HSI mode</td></tr>
<tr><td><b>light=N&amp;mode=ANM&amp;scene=1&amp;bri=50</b></td><td>Set a light to a built-in scene</td></tr>
<tr><td><b>turnoff / turnon</b></td><td>Power lights off or on</td></tr>
<tr><td><b>use_preset=N</b></td><td>Recall preset N</td></tr>
<tr><td><b>animate=Name|speed|rate|bri|loop|maxLoops|revert</b></td>
    <td>Play an animation. Only the name is required. The rest are positional and optional:
    speed (1.0), rate (5), brightness percent (80), loop (true/false), maxLoops (0 for
    endless), revert (true/false).</td></tr>
<tr><td><b>stop_animate</b></td><td>Stop the running animation</td></tr>
<tr><td><b>list / list_json</b></td><td>List lights, presets, and animations</td></tr>
</table>
<p>POST to <code>/NeewerLux/batch</code> for multi-light JSON commands, or to
<code>/NeewerLux/animate</code> for JSON animation control.</p>

<hr>

<p style="color:#888; font-size:0.9em;">
<b>Repository:</b> <a href="https://github.com/poizenjam/NeewerLux/">github.com/poizenjam/NeewerLux</a><br>
<b>Releases:</b> <a href="https://github.com/poizenjam/NeewerLux/releases">github.com/poizenjam/NeewerLux/releases</a><br><br>
Based on <a href="https://github.com/taburineagle/NeewerLite-Python/">NeewerLite-Python</a> (v0.12d) by Zach Glenwright.
Originally from <a href="https://github.com/keefo/NeewerLite">NeewerLite</a> by Xu Lian.
</p>
""")
        infoLay.addWidget(self.infoText)
        self.ColorModeTabWidget.addTab(self.infoTab, "Info")

        # --- LOG TAB ---
        self.logTab = QWidget()
        logLay = QVBoxLayout(self.logTab)
        logLay.setContentsMargins(10, 10, 10, 10)
        logLay.setSpacing(4)
        logToolbar = QHBoxLayout()
        self.logClearButton = QPushButton("Clear")
        self.logClearButton.setToolTip("Clear the log display")
        self.logSaveButton = QPushButton("Save Log")
        self.logSaveButton.setToolTip("Save the current log to a file")
        logToolbar.addWidget(self.logClearButton)
        logToolbar.addWidget(self.logSaveButton)
        logToolbar.addStretch(1)
        logLay.addLayout(logToolbar)
        self.logTextEdit = QPlainTextEdit()
        self.logTextEdit.setReadOnly(True)
        self.logTextEdit.setFont(_monoFont(9))
        self.logTextEdit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.logTextEdit.setMaximumBlockCount(2000)  # cap log at 2000 lines to prevent unbounded growth (CPU creep)
        logLay.addWidget(self.logTextEdit)
        self.ColorModeTabWidget.addTab(self.logTab, "Log")

        # --- SOUND REACTIVE ---
        # Added last so the indexes of the tabs above (used throughout NeewerLux.py) stay the same.
        self.soundTab = QWidget()
        sndLay = QVBoxLayout(self.soundTab)
        sndLay.setContentsMargins(10, 10, 10, 10)
        sndLay.setSpacing(6)

        presetRow = QHBoxLayout()
        presL = QLabel("Preset:"); presL.setFont(mainFont); presetRow.addWidget(presL)
        self.soundPresetCombo = QComboBox()
        self.soundPresetCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.soundPresetCombo.setToolTip("Saved Sound settings. Pick one to load it.\n"
            "The input device and beat source are not part of a preset.")
        presetRow.addWidget(self.soundPresetCombo, 1)
        self.soundPresetSaveButton = QPushButton("Save...")
        self.soundPresetSaveButton.setToolTip("Save the current Sound settings as a preset\n(use an existing name to overwrite it)")
        presetRow.addWidget(self.soundPresetSaveButton)
        self.soundPresetDeleteButton = QPushButton("Delete")
        self.soundPresetDeleteButton.setToolTip("Delete the selected preset")
        presetRow.addWidget(self.soundPresetDeleteButton)
        sndLay.addLayout(presetRow)

        devRow = QHBoxLayout()
        devL = QLabel("Listen to:"); devL.setFont(mainFont); devRow.addWidget(devL)
        self.soundDeviceCombo = QComboBox()
        self.soundDeviceCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.soundDeviceCombo.setToolTip("Audio input to analyse. To react to what your computer plays,\n"
            "pick a loopback device (BlackHole on macOS, Stereo Mix / VB-Cable on Windows,\n"
            "'Monitor of ...' on Linux). See the note below.")
        devRow.addWidget(self.soundDeviceCombo, 1)
        self.soundRefreshButton = QPushButton("Refresh")
        devRow.addWidget(self.soundRefreshButton)
        sndLay.addLayout(devRow)

        sg = QGridLayout(); sg.setHorizontalSpacing(8); sg.setVerticalSpacing(4)
        modeL = QLabel("Mode:"); modeL.setFont(mainFont); sg.addWidget(modeL, 0, 0)
        self.soundModeCombo = QComboBox(); sg.addWidget(self.soundModeCombo, 0, 1, 1, 3)
        self.soundModeHelp = QLabel(""); self.soundModeHelp.setWordWrap(True)
        self.soundModeHelp.setProperty("dim", True)
        sg.addWidget(self.soundModeHelp, 1, 0, 1, 4)

        def _spin(lo, hi, val, suffix=""):
            sp = SpinBoxWithButtons(minVal=lo, maxVal=hi, value=val, suffix=suffix)
            return sp
        sensL = QLabel("Sensitivity:"); sensL.setFont(mainFont); sg.addWidget(sensL, 2, 0)
        self.soundSensSpin = _spin(25, 400, 100, "%")
        self.soundSensSpin.setToolTip("Higher = quieter parts light up more and more beats are detected.\nLower = only the loudest peaks and strongest beats show.")
        sg.addWidget(self.soundSensSpin, 2, 1)
        smL = QLabel("Smoothing:"); smL.setFont(mainFont); sg.addWidget(smL, 2, 2)
        self.soundSmoothSpin = _spin(0, 95, 50, "%")
        self.soundSmoothSpin.setToolTip("0% = snappy and flickery, 95% = slow and smooth")
        sg.addWidget(self.soundSmoothSpin, 2, 3)
        minL = QLabel("Min bright:"); minL.setFont(mainFont); sg.addWidget(minL, 3, 0)
        self.soundMinBriSpin = _spin(0, 100, 5, "%"); sg.addWidget(self.soundMinBriSpin, 3, 1)
        maxL = QLabel("Max bright:"); maxL.setFont(mainFont); sg.addWidget(maxL, 3, 2)
        self.soundMaxBriSpin = _spin(1, 100, 100, "%"); sg.addWidget(self.soundMaxBriSpin, 3, 3)
        satL = QLabel("Saturation:"); satL.setFont(mainFont); sg.addWidget(satL, 4, 0)
        self.soundSatSpin = _spin(0, 100, 100, "%"); sg.addWidget(self.soundSatSpin, 4, 1)
        cfL = QLabel("Colour fade:"); cfL.setFont(mainFont); sg.addWidget(cfL, 4, 2)
        self.soundColourFadeSpin = _spin(0, 95, 75, "%")
        self.soundColourFadeSpin.setToolTip("How smoothly Bass pulse and Beat colour jump move between colours.\n"
            "Beat colour jump: the share of the time until the next change spent gliding (95% = always moving).\n"
            "0% = hard cuts. Separate from Smoothing, so brightness can stay punchy.")
        sg.addWidget(self.soundColourFadeSpin, 4, 3)
        rateL = QLabel("Rate:"); rateL.setFont(mainFont); sg.addWidget(rateL, 5, 0)
        self.soundRateSpin = _spin(2, 30, 15, "/s")
        self.soundRateSpin.setToolTip("Colour updates per second sent to the lights.\n"
            "About 15/s is the most Bluetooth handles reliably; frames are skipped if the lights fall behind.")
        sg.addWidget(self.soundRateSpin, 5, 1)
        self.soundAllLightsCheck = QCheckBox("All lights (else the selected ones)")
        self.soundAllLightsCheck.setChecked(True)
        sg.addWidget(self.soundAllLightsCheck, 5, 2, 1, 2)
        colL = QLabel("Colours:"); colL.setFont(mainFont); sg.addWidget(colL, 6, 0)
        self.soundPalette = PaletteEditor()
        sg.addWidget(self.soundPalette, 6, 1, 1, 3)
        beatL = QLabel("Beats from:"); beatL.setFont(mainFont); sg.addWidget(beatL, 7, 0)
        self.soundBeatSourceCombo = QComboBox()
        self.soundBeatSourceCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.soundBeatSourceCombo.setToolTip("Where beats come from. A MIDI clock input (Traktor Virtual Output, say)\n"
            "gives the exact tempo and beat, so beat effects never miss. If the clock stops,\n"
            "beats are detected from the sound again until it comes back.")
        sg.addWidget(self.soundBeatSourceCombo, 7, 1, 1, 2)
        self.soundClockBadge = QLabel("")
        self.soundClockBadge.setToolTip("MIDI clock link: green when beats come from the clock")
        sg.addWidget(self.soundClockBadge, 7, 3)
        leadL = QLabel("Beat lead:"); leadL.setFont(mainFont); sg.addWidget(leadL, 8, 0)
        self.soundClockLeadSpin = _spin(0, 300, 50, " ms")
        self.soundClockLeadSpin.setToolTip("Fire MIDI clock beats, and beats predicted from the tempo, this much early,\nto make up for the time "
            "Bluetooth takes to reach the lights. Raise it if the lights land after the kick.")
        sg.addWidget(self.soundClockLeadSpin, 8, 1)
        everyL = QLabel("Colour every:"); everyL.setFont(mainFont); sg.addWidget(everyL, 8, 2)
        self.soundBeatsPerColourSpin = _spin(1, 16, 1, " beats")
        self.soundBeatsPerColourSpin.setToolTip("Beat colour jump: change colour every this many beats (4 = once a bar).\n"
            "Brightness still flashes on every beat. With a MIDI clock, changes land on bar lines.")
        sg.addWidget(self.soundBeatsPerColourSpin, 8, 3)
        self.soundClockNeedsSoundCheck = QCheckBox("Clock beats only while music plays")
        self.soundClockNeedsSoundCheck.setChecked(True)
        self.soundClockNeedsSoundCheck.setToolTip("Traktor keeps sending MIDI clock after the decks stop. With this on,\n"
            "clock beats pause after 1.5 s of quiet and come back with the sound.")
        sg.addWidget(self.soundClockNeedsSoundCheck, 9, 1, 1, 3)
        self.soundPredictBeatsCheck = QCheckBox("Predict beats from the tempo")
        self.soundPredictBeatsCheck.setChecked(True)
        self.soundPredictBeatsCheck.setToolTip("Without a MIDI clock: find the tempo in the sound (about 4 s after the kicks start)\n"
            "and fire each beat on time, early by the beat lead, instead of after each kick is heard.\n"
            "Off: every kick flashes as it is heard, about 30 ms late plus the Bluetooth delay.")
        sg.addWidget(self.soundPredictBeatsCheck, 10, 1, 1, 3)
        sndLay.addLayout(sg)

        meterRow = QHBoxLayout()
        self.soundMeters = {}
        for key, label in (("bass", "Bass"), ("mid", "Mid"), ("high", "High"), ("level", "Level")):
            col = QVBoxLayout(); col.setSpacing(2)
            bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0); bar.setTextVisible(False)
            bar.setFixedHeight(10)
            col.addWidget(QLabel(label)); col.addWidget(bar)
            meterRow.addLayout(col, 1)
            self.soundMeters[key] = bar
        self.soundSwatch = QLabel("")
        self.soundSwatch.setFixedSize(44, 32)
        self.soundSwatch.setToolTip("Colour being sent to the first light")
        self.soundSwatch.setStyleSheet("background-color: #000; border: 1px solid #555; border-radius: 4px;")
        meterRow.addWidget(self.soundSwatch)
        sndLay.addLayout(meterRow)

        btnRow = QHBoxLayout()
        self.soundStartButton = QPushButton("\u25B6 Start")
        self.soundStopButton = QPushButton("\u25A0 Stop")
        self.soundStopButton.setEnabled(False)
        btnRow.addWidget(self.soundStartButton); btnRow.addWidget(self.soundStopButton)
        sndLay.addLayout(btnRow)
        self.soundStatusLabel = QLabel("Stopped"); self.soundStatusLabel.setWordWrap(True)
        sndLay.addWidget(self.soundStatusLabel)
        self.soundSetupNote = QLabel(
            "To follow what your computer is playing: macOS needs a loopback device such as BlackHole. "
            "In Audio MIDI Setup create a Multi-Output Device with your speakers and BlackHole, make it the "
            "sound output, then listen to BlackHole here. Windows: enable Stereo Mix or install VB-Cable. "
            "Linux: pick a 'Monitor of ...' source.\n\n"
            "Beats from Traktor: Preferences > MIDI Clock > tick Send MIDI Clock; in Controller Manager add a "
            "Generic MIDI device with Out-Port 'Traktor Virtual Output'; press the clock-send button in the Master "
            "Clock panel. Then pick 'Traktor Virtual Output' under Beats from. Press Sync in Traktor's Master "
            "Clock panel if the bar count drifts off the downbeat.")
        self.soundSetupNote.setWordWrap(True)
        self.soundSetupNote.setProperty("dim", True)
        sndLay.addWidget(self.soundSetupNote)
        sndLay.addStretch(1)

        soundScroll = QScrollArea()
        soundScroll.setWidgetResizable(True)
        soundScroll.setFrameShape(QFrame.NoFrame)
        soundScroll.setWidget(self.soundTab)
        self.ColorModeTabWidget.addTab(soundScroll, "Sound")

        # === ASSEMBLE ===
        bottomLay.addWidget(self.ColorModeTabWidget, 1)
        
        # Apply button, shown when live preview is disabled
        self.applyButton = QPushButton("Apply Settings")
        self.applyButton.setObjectName("applyButton")
        self.applyButton.setMinimumHeight(32)
        self.applyButton.setVisible(False)  # hidden when live preview is on
        bottomLay.addWidget(self.applyButton)
        self.mainSplitter.addWidget(self.presetScrollArea)
        self.mainSplitter.addWidget(bottomPanel)
        self.mainSplitter.setStretchFactor(0, 3)  # light table
        self.mainSplitter.setStretchFactor(1, 1)  # presets
        self.mainSplitter.setStretchFactor(2, 4)  # tabs
        self.mainSplitter.setSizes([260, 72, 380])  # initial sizes
        mainLayout.addWidget(self.mainSplitter, 1)

        # === STATUS BAR ===
        self.statusBar = QStatusBar()
        MainWindow.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Welcome to NeewerLux!")
