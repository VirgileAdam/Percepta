
from __future__ import annotations

import base64
import io
import math
import sys
import ctypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_VERSION = "0.32.0"

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageOps



from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QProgressDialog,
    QScrollArea, QSlider, QSpinBox, QSplashScreen, QStyle, QTabWidget, QVBoxLayout, QWidget
)



def set_windows_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "VirgileAdam.Percepta.2026"
        )
    except Exception:
        pass


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


@dataclass
class Settings:
    pattern: str = "Auto"
    density: int = 14
    strength: float = 0.80
    colour_separation: int = 10
    contrast: float = 1.55
    output_size: int = 1600
    zoom: float = 1.0
    pan_x: int = 0
    pan_y: int = 0
    rotation: float = 0.0
    crop_ratio: str = "Square"
    line_smoothing: int = 6
    halftone_shape: str = "Circle"
    halftone_angle: float = 0.0
    halftone_min_size: float = 0.35
    spiral_center_x: float = 50.0
    spiral_center_y: float = 50.0
    spiral_clockwise: bool = True
    spiral_smoothing: int = 6


class ImageView(QScrollArea):
    def __init__(self, placeholder: str):
        super().__init__()
        self.setMinimumSize(360, 360)
        self.setSizePolicy(
            self.sizePolicy().Policy.Expanding,
            self.sizePolicy().Policy.Expanding
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.label = QLabel(placeholder)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("QLabel { background:#202124; color:#c8c8c8; }")
        self.setWidget(self.label)
        self.setWidgetResizable(True)
        self._pixmap: Optional[QPixmap] = None

    def set_image(self, image: Image.Image):
        arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
        qimg = QImage(
            arr.data, arr.shape[1], arr.shape[0], arr.strides[0],
            QImage.Format.Format_RGB888
        ).copy()
        self._pixmap = QPixmap.fromImage(qimg)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if self._pixmap is None:
            return
        side = max(1, min(self.viewport().width(), self.viewport().height()) - 6)
        self.label.setPixmap(self._pixmap.scaled(
            side,
            side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))


def center_square(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def framed_source(image: Image.Image, settings: Settings) -> Image.Image:
    """Interactive framing: rotation, zoom, pan and crop-ratio presets."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    if abs(settings.rotation) > 1e-6:
        image = image.rotate(
            settings.rotation,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor="black"
        )

    ratios = {"Square": 1.0, "Portrait 4:5": 4/5, "Landscape 4:3": 4/3}
    ratio = ratios.get(settings.crop_ratio, 1.0)
    width, height = image.size

    if width / height >= ratio:
        crop_h = height / max(1.0, settings.zoom)
        crop_w = crop_h * ratio
    else:
        crop_w = width / max(1.0, settings.zoom)
        crop_h = crop_w / ratio

    crop_w = min(width, max(32.0, crop_w))
    crop_h = min(height, max(32.0, crop_h))
    max_dx = max(0.0, (width - crop_w) / 2.0)
    max_dy = max(0.0, (height - crop_h) / 2.0)
    cx = width / 2.0 + max_dx * settings.pan_x / 100.0
    cy = height / 2.0 + max_dy * settings.pan_y / 100.0
    left = int(round(max(0, min(width - crop_w, cx - crop_w / 2))))
    top = int(round(max(0, min(height - crop_h, cy - crop_h / 2))))
    crop = image.crop((left, top, int(left + crop_w), int(top + crop_h)))

                                                                                     
    return ImageOps.pad(
        crop,
        (settings.output_size, settings.output_size),
        method=Image.Resampling.LANCZOS,
        color="black",
        centering=(0.5, 0.5)
    )


def prepare(image: Image.Image, settings: Settings) -> Image.Image:
    image = framed_source(image, settings)
    return ImageEnhance.Contrast(image).enhance(settings.contrast)


def rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image, dtype=np.float32) / 255.0


def luminance(array: np.ndarray) -> np.ndarray:
    return 0.2126 * array[..., 0] + 0.7152 * array[..., 1] + 0.0722 * array[..., 2]


def smooth_1d(values: np.ndarray, radius: int = 6) -> np.ndarray:
    radius = max(0, int(round(radius)))
    if radius == 0:
        return values.copy()
    kernel = np.ones(radius * 2 + 1, dtype=np.float32) / (radius * 2 + 1)
    return np.convolve(np.pad(values, (radius, radius), mode="edge"), kernel, mode="valid")


def choose_pattern(image: Image.Image) -> str:
                                                                       
    gray = np.asarray(center_square(image).convert("L").resize((192, 192)),
                      dtype=np.float32) / 255.0
    detail = (np.abs(np.diff(gray, axis=0)).mean()
              + np.abs(np.diff(gray, axis=1)).mean())
    return "Halftone" if detail > 0.12 else "Vertical stripes"


def render_axis_stripes(image: Image.Image, settings: Settings, horizontal: bool) -> Image.Image:
    source = image.transpose(Image.Transpose.ROTATE_90) if horizontal else image
    arr = rgb_array(source)
    size = settings.output_size
    count = max(4, settings.density)
    period = size / count
    centres = (np.arange(count) + 0.5) * period
    max_width = period * 0.66
    min_width = max(1.0, period * 0.018)
    output = np.zeros((size, size, 3), dtype=np.uint8)
    shifts = (-settings.colour_separation, 0, settings.colour_separation)

    for centre in centres:
        x0 = max(0, int(centre - period * 0.30))
        x1 = min(size, int(centre + period * 0.30) + 1)
        values = arr[:, x0:x1, :].mean(axis=1)
        for channel in range(3):
            values[:, channel] = smooth_1d(values[:, channel], settings.line_smoothing)

        widths = min_width + (max_width - min_width) * np.clip(
            np.power(values, 0.82) * settings.strength, 0, 1
        )

        for channel, shift in enumerate(shifts):
            left = np.rint(centre + shift - widths[:, channel] / 2).astype(int)
            right = np.rint(centre + shift + widths[:, channel] / 2).astype(int)
            for y in range(size):
                a = max(0, left[y])
                b = min(size, right[y])
                if b > a:
                    output[y, a:b, channel] = 255

    result = Image.fromarray(output)
    return result.transpose(Image.Transpose.ROTATE_270) if horizontal else result


def render_diagonal_stripes(image: Image.Image, settings: Settings) -> Image.Image:
                                                                                    
    size = settings.output_size
    enlarged = int(math.ceil(size * math.sqrt(2)))
    canvas = Image.new("RGB", (enlarged, enlarged), "black")
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    canvas.paste(resized, ((enlarged - size)//2, (enlarged - size)//2))
    rotated = canvas.rotate(45, resample=Image.Resampling.BICUBIC, expand=False)

    local = Settings(
        pattern=settings.pattern,
        density=max(6, int(settings.density * 1.35)),
        strength=settings.strength,
        colour_separation=settings.colour_separation,
        contrast=1.0,
        output_size=enlarged,
        line_smoothing=settings.line_smoothing,
        halftone_shape=settings.halftone_shape,
        halftone_angle=settings.halftone_angle,
        halftone_min_size=settings.halftone_min_size,
        spiral_center_x=settings.spiral_center_x,
        spiral_center_y=settings.spiral_center_y,
        spiral_clockwise=settings.spiral_clockwise,
        spiral_smoothing=settings.spiral_smoothing
    )
    striped = render_axis_stripes(rotated, local, horizontal=False)
    restored = striped.rotate(-45, resample=Image.Resampling.BICUBIC, expand=False)
    left = (enlarged - size)//2
    return restored.crop((left, left, left + size, left + size))


def render_halftone(image: Image.Image, settings: Settings, hexagonal: bool = False) -> Image.Image:
    angle = settings.halftone_angle
    source = image.rotate(angle, Image.Resampling.BICUBIC, expand=False, fillcolor="black") if angle else image
    arr = rgb_array(source)
    size = settings.output_size
    cells = max(12, int(settings.density * 2.5))
    step = size / cells
    masks = [Image.new("L", (size, size), 0) for _ in range(3)]
    draws = [ImageDraw.Draw(mask) for mask in masks]
    shifts = (-settings.colour_separation, 0, settings.colour_separation)
    y_step = step * (math.sqrt(3) / 2) if hexagonal else step
    rows = int(math.ceil(size / y_step)) + 1

    for row in range(rows):
        cy = (row + 0.5) * y_step
        offset = step * 0.5 if hexagonal and row % 2 else 0.0
        for column in range(cells + (1 if hexagonal else 0)):
            cx = (column + 0.5) * step + offset
            if cx >= size or cy >= size:
                continue
            r_sample = max(1, int(step * 0.36))
            x0, x1 = max(0, int(cx)-r_sample), min(size, int(cx)+r_sample+1)
            y0, y1 = max(0, int(cy)-r_sample), min(size, int(cy)+r_sample+1)
            if x1 <= x0 or y1 <= y0:
                continue
            rgb = arr[y0:y1, x0:x1].mean(axis=(0, 1))
            for channel, shift in enumerate(shifts):
                value = float(np.clip(rgb[channel] * settings.strength, 0, 1))
                radius = max(settings.halftone_min_size, step * 0.47 * math.sqrt(value))
                box = (cx-radius+shift*.25, cy-radius, cx+radius+shift*.25, cy+radius)
                shape = settings.halftone_shape
                if shape == "Square":
                    draws[channel].rectangle(box, fill=255)
                elif shape == "Diamond":
                    px = cx + shift*.25
                    draws[channel].polygon(
                        [(px, cy-radius), (px+radius, cy),
                         (px, cy+radius), (px-radius, cy)],
                        fill=255
                    )
                else:
                    draws[channel].ellipse(box, fill=255)

    channels = [np.asarray(mask, dtype=np.uint8) for mask in masks]
    result = Image.fromarray(np.stack(channels, axis=2), "RGB")
    return result.rotate(-angle, Image.Resampling.BICUBIC, expand=False, fillcolor="black") if angle else result


def render_rings(image: Image.Image, settings: Settings) -> Image.Image:
    arr = rgb_array(image)
    size = settings.output_size
    cells = max(10, int(settings.density * 2.0))
    step = size / cells
    output = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(output)
    shifts = (-settings.colour_separation, 0, settings.colour_separation)

    for gy in range(cells):
        for gx in range(cells):
            x0 = int(gx * step)
            x1 = max(x0 + 1, int((gx + 1) * step))
            y0 = int(gy * step)
            y1 = max(y0 + 1, int((gy + 1) * step))
            rgb = arr[y0:y1, x0:x1].mean(axis=(0, 1))
            cx = (gx + 0.5) * step
            cy = (gy + 0.5) * step
            outer = step * 0.43

            for channel, shift in enumerate(shifts):
                value = float(np.clip(rgb[channel] * settings.strength, 0, 1))
                thickness = max(1, int(step * (0.035 + 0.24 * value)))
                colour = [0, 0, 0]
                colour[channel] = 255
                draw.ellipse(
                    (cx - outer + shift*0.22, cy - outer,
                     cx + outer + shift*0.22, cy + outer),
                    outline=tuple(colour),
                    width=thickness
                )
    return output


def render_crosshatch(image: Image.Image, settings: Settings) -> Image.Image:
                                                                              
    arr = rgb_array(image)
    size = settings.output_size
    cells = max(12, int(settings.density * 2.2))
    step = size / cells
    output = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(output)
    shifts = (-settings.colour_separation, 0, settings.colour_separation)

    for gy in range(cells):
        for gx in range(cells):
            x0 = gx * step
            y0 = gy * step
            x1 = (gx + 1) * step
            y1 = (gy + 1) * step
            sx0 = int(x0)
            sx1 = max(sx0 + 1, int(x1))
            sy0 = int(y0)
            sy1 = max(sy0 + 1, int(y1))
            rgb = arr[sy0:sy1, sx0:sx1].mean(axis=(0,1))

            for channel, shift in enumerate(shifts):
                value = float(np.clip(rgb[channel] * settings.strength, 0, 1))
                width = max(1, int(step * (0.035 + 0.20 * value)))
                colour = [0, 0, 0]
                colour[channel] = 255
                if (gx + gy + channel) % 2 == 0:
                    draw.line(
                        (x0 + shift*0.18, y1, x1 + shift*0.18, y0),
                        fill=tuple(colour), width=width
                    )
                else:
                    draw.line(
                        (x0 + shift*0.18, y0, x1 + shift*0.18, y1),
                        fill=tuple(colour), width=width
                    )
    return output


def render_truchet(image: Image.Image, settings: Settings) -> Image.Image:
                                                                                        
    arr = rgb_array(image)
    size = settings.output_size
    cells = max(10, int(settings.density * 1.8))
    step = size / cells
    output = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(output)
    shifts = (-settings.colour_separation, 0, settings.colour_separation)

    for gy in range(cells):
        for gx in range(cells):
            x0 = gx * step
            y0 = gy * step
            x1 = (gx + 1) * step
            y1 = (gy + 1) * step
            sx0, sx1 = int(x0), max(int(x1), int(x0)+1)
            sy0, sy1 = int(y0), max(int(y1), int(y0)+1)
            rgb = arr[sy0:sy1, sx0:sx1].mean(axis=(0,1))

            orientation = (gx + gy) % 2
            for channel, shift in enumerate(shifts):
                value = float(np.clip(rgb[channel] * settings.strength, 0, 1))
                width = max(1, int(step * (0.035 + 0.23 * value)))
                colour = [0,0,0]
                colour[channel] = 255
                dx = shift * 0.18

                if orientation == 0:
                    draw.arc((x0-step/2+dx, y0-step/2, x0+step/2+dx, y0+step/2),
                             0, 90, fill=tuple(colour), width=width)
                    draw.arc((x1-step/2+dx, y1-step/2, x1+step/2+dx, y1+step/2),
                             180, 270, fill=tuple(colour), width=width)
                else:
                    draw.arc((x1-step/2+dx, y0-step/2, x1+step/2+dx, y0+step/2),
                             90, 180, fill=tuple(colour), width=width)
                    draw.arc((x0-step/2+dx, y1-step/2, x0+step/2+dx, y1+step/2),
                             270, 360, fill=tuple(colour), width=width)
    return output



def _spiral_geometry(size: int, turns: int, settings: Settings):
    cx = (size - 1) * settings.spiral_center_x / 100.0
    cy = (size - 1) * settings.spiral_center_y / 100.0
    corner_radius = max(
        math.hypot(cx, cy),
        math.hypot(size-1-cx, cy),
        math.hypot(cx, size-1-cy),
        math.hypot(size-1-cx, size-1-cy)
    ) * 1.015
    theta_max = turns * 2.0 * math.pi
    growth = corner_radius / theta_max
    estimated_length = 0.5 * growth * (
        theta_max * math.sqrt(1.0 + theta_max * theta_max)
        + math.asinh(theta_max)
    )
    point_count = max(12000, min(150000, int(estimated_length * 2.0)))
    direction = -1.0 if settings.spiral_clockwise else 1.0
    theta = direction * np.linspace(0.0, theta_max, point_count, dtype=np.float32)
    radius = growth * np.abs(theta)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    x, y = cx + radius*cos_t, cy + radius*sin_t
    dx = direction*growth*cos_t - radius*sin_t
    dy = direction*growth*sin_t + radius*cos_t
    norm = np.maximum(np.hypot(dx, dy), 1e-6)
    nx, ny = -dy/norm, dx/norm
    return x, y, nx, ny, point_count, corner_radius / turns


def _smooth_along_path(values: np.ndarray, point_count: int, turns: int, settings: Settings) -> np.ndarray:
    """Smooth local values along the spiral while retaining recognizable detail."""
    smooth_radius = max(
        1,
        int(round(
            (point_count / max(900, turns * 75))
            * max(1, int(settings.spiral_smoothing)) / 6.0
        ))
    )
    kernel = np.ones(int(smooth_radius * 2 + 1), dtype=np.float32)
    kernel /= kernel.sum()

    if values.ndim == 1:
        return np.convolve(
            np.pad(values, (int(smooth_radius), int(smooth_radius)), mode="edge"),
            kernel,
            mode="valid"
        )

    result = values.copy()
    for channel in range(values.shape[1]):
        result[:, channel] = np.convolve(
            np.pad(values[:, channel], (int(smooth_radius), int(smooth_radius)), mode="edge"),
            kernel,
            mode="valid"
        )
    return result


def render_spiral_halftone(
    image: Image.Image,
    settings: Settings
) -> Image.Image:
    """
    One continuous spiral using exactly the same colour logic as the line modes.

    Three independent spiral strokes are rendered into separate red, green and
    blue channel masks. Their local widths are calculated independently from
    the corresponding source channel. The strokes are shifted across the normal
    by Colour separation.

    Where the three channel strokes overlap, the additive result is white.
    Partial overlap naturally produces yellow, cyan and magenta, reproducing the
    same white-centred RGB fringes as the diagonal, horizontal and vertical lines.
    """
    arr = rgb_array(image)
    size = settings.output_size
    turns = max(12, int(round(settings.density * 2.15)))

    x, y, nx, ny, point_count, turn_spacing = _spiral_geometry(size, turns, settings)

    xi = np.clip(np.rint(x).astype(np.int32), 0, size - 1)
    yi = np.clip(np.rint(y).astype(np.int32), 0, size - 1)
    values = arr[yi, xi, :].copy()
    values = _smooth_along_path(values, point_count, turns, settings)

    min_width = max(1.0, turn_spacing * 0.018)
    max_width = max(min_width + 1.0, turn_spacing * 0.88)
    widths = min_width + (max_width - min_width) * np.clip(
        np.power(values, 0.82) * settings.strength,
        0.0, 1.0
    )

                                                              
    separation = min(
        float(settings.colour_separation),
        turn_spacing * 0.95
    )
    offsets = (-separation, 0.0, separation)

                                                                               
                                                                              
    masks = [Image.new("L", (size, size), 0) for _ in range(3)]
    draws = [ImageDraw.Draw(mask) for mask in masks]

    segment_step = max(1, int(point_count / 36000))
    previous = 0

    for index in range(segment_step, point_count, segment_step):
        for channel in range(3):
            offset = offsets[channel]
            p0 = (
                float(x[previous] + nx[previous] * offset),
                float(y[previous] + ny[previous] * offset)
            )
            p1 = (
                float(x[index] + nx[index] * offset),
                float(y[index] + ny[index] * offset)
            )

            pixel_width = max(1, int(round(float(widths[index, channel]))))
            draws[channel].line((p0, p1), fill=255, width=pixel_width)

                                                                                
            joint_radius = pixel_width / 2.0
            draws[channel].ellipse(
                (
                    p1[0] - joint_radius,
                    p1[1] - joint_radius,
                    p1[0] + joint_radius,
                    p1[1] + joint_radius
                ),
                fill=255
            )

        previous = index

    channels = [np.asarray(mask, dtype=np.uint8) for mask in masks]
    return Image.fromarray(np.stack(channels, axis=2), "RGB")


def generate(image: Image.Image, settings: Settings) -> tuple[Image.Image, str]:
    prepared = prepare(image, settings)
    pattern = settings.pattern if settings.pattern else "Vertical stripes"

    if pattern == "Vertical stripes":
        result = render_axis_stripes(prepared, settings, horizontal=False)
    elif pattern == "Horizontal stripes":
        result = render_axis_stripes(prepared, settings, horizontal=True)
    elif pattern == "Diagonal stripes":
        result = render_diagonal_stripes(prepared, settings)
    elif pattern == "Halftone":
        result = render_halftone(prepared, settings, hexagonal=False)
    elif pattern == "Hexagonal halftone":
        result = render_halftone(prepared, settings, hexagonal=True)
    elif pattern == "Spiral stripes":
        result = render_spiral_halftone(prepared, settings)
    else:
        result = render_axis_stripes(prepared, settings, horizontal=False)

    return result, pattern



class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Professional export")
        form = QFormLayout(self)
        self.format = QComboBox()
        self.format.addItems(["PNG", "TIFF", "PDF", "SVG"])
        form.addRow("Format", self.format)
        self.background = QComboBox()
        self.background.addItems(["Black", "White", "Transparent"])
        form.addRow("Background", self.background)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        form.addRow("Resolution", self.dpi)
        self.width_cm = QDoubleSpinBox()
        self.width_cm.setRange(1.0, 300.0)
        self.width_cm.setValue(20.0)
        self.width_cm.setSuffix(" cm")
        form.addRow("Print width", self.width_cm)
        self.bleed = QDoubleSpinBox()
        self.bleed.setRange(0.0, 20.0)
        self.bleed.setValue(0.0)
        self.bleed.setSuffix(" mm")
        form.addRow("Bleed / margin", self.bleed)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


REFERENCE_OUTPUT_SIZE = 1600

PATTERN_PARAMETER_PROFILES = {
    "Vertical stripes": {
        "label": "Number of stripes",
        "minimum": 4,
        "maximum": 400,
        "default": 14,
        "animation_start": 8,
        "animation_end": 24,
        "tooltip": "Total number of vertical stripes across the output."
    },
    "Horizontal stripes": {
        "label": "Number of stripes",
        "minimum": 4,
        "maximum": 400,
        "default": 14,
        "animation_start": 8,
        "animation_end": 24,
        "tooltip": "Total number of horizontal stripes across the output."
    },
    "Diagonal stripes": {
        "label": "Number of stripes",
        "minimum": 4,
        "maximum": 500,
        "default": 18,
        "animation_start": 10,
        "animation_end": 28,
        "tooltip": "Approximate number of diagonal stripes crossing the output."
    },
    "Halftone": {
        "label": "Dot spacing",
        "minimum": 3,
        "maximum": 160,
        "default": 12,
        "animation_start": 24,
        "animation_end": 7,
        "suffix": " px",
        "tooltip": "Distance, in output pixels, between neighbouring dot centres. Smaller values create more dots."
    },
    "Hexagonal halftone": {
        "label": "Dot spacing",
        "minimum": 3,
        "maximum": 160,
        "default": 12,
        "animation_start": 24,
        "animation_end": 7,
        "suffix": " px",
        "tooltip": "Distance, in output pixels, between neighbouring dot centres in the hexagonal grid. Smaller values create more dots."
    },
    "Spiral stripes": {
        "label": "Turn spacing",
        "minimum": 3,
        "maximum": 160,
        "default": 19,
        "animation_start": 24,
        "animation_end": 6,
        "suffix": " px",
        "tooltip": "Radial spacing, in output pixels, between two successive spiral turns. Smaller values create more turns."
    },
}

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Percepta")
        self.setWindowIcon(QIcon(str(resource_path("assets/percepta_icon.png"))))
        self.resize(1125, 590)
        self.setMinimumSize(1060, 540)

        self.source: Optional[Image.Image] = None
        self.result: Optional[Image.Image] = None
        self.path: Optional[Path] = None
        self.animation_frames: list[Image.Image] = []
        self.animation_index = 0
        self.animation_delay_ms = 90
        self.animation_fps = 12

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.regenerate)
        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.show_next_animation_frame)

        self.build_ui()
        self.build_menu()
        self.setAcceptDrops(True)
        QTimer.singleShot(0, self.fit_window_width)

    def fit_window_width(self):
        """Fit the window to the actual horizontal content without extra blank space."""
        target = 1125
        screen = QApplication.primaryScreen()
        if screen is not None:
            target = min(target, max(980, screen.availableGeometry().width() - 40))
        self.resize(target, self.height())

    def build_menu(self):
        menu = self.menuBar().addMenu("&File")

        action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "&Open image…", self
        )
        action.setShortcut("Ctrl+O")
        action.triggered.connect(self.open_image)
        menu.addAction(action)

        action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "&Export…", self
        )
        action.setShortcut("Ctrl+S")
        action.triggered.connect(self.export_professional)
        menu.addAction(action)

        menu.addSeparator()
        action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton),
            "&Quit", self
        )
        action.setShortcut("Ctrl+Q")
        action.triggered.connect(self.close)
        menu.addAction(action)

        help_menu = self.menuBar().addMenu("&Help")

        action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton),
            "&How it works…", self
        )
        action.setShortcut("F1")
        action.triggered.connect(self.show_how_it_works)
        help_menu.addAction(action)

        action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView),
            "&About Percepta", self
        )
        action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(action)

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About Percepta")
        dialog.setWindowIcon(QIcon(str(resource_path("assets/percepta_icon.png"))))
        dialog.setFixedSize(455, 225)

        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        content = QHBoxLayout()
        content.setSpacing(14)

        icon_label = QLabel()
        pixmap = QPixmap(str(resource_path("assets/percepta_icon.png")))
        icon_label.setPixmap(
            pixmap.scaled(
                96,
                96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )
        icon_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        icon_label.setFixedWidth(100)
        content.addWidget(icon_label, 0)

        information = QVBoxLayout()
        information.setContentsMargins(0, 0, 0, 0)
        information.setSpacing(4)

        title = QLabel("<span style='font-size:25px; font-weight:700;'>Percepta</span>")
        information.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        information.addWidget(version)

        description = QLabel("Perceptual pattern image generator")
        description.setStyleSheet("font-size: 15px;")
        information.addWidget(description)

        author = QLabel(
            '© 2026 <a href="https://www.virgile-adam.com">Virgile Adam</a>'
        )
        author.setOpenExternalLinks(True)
        author.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        information.addWidget(author)

        affiliation = QLabel("IBS – CNRS – Université Grenoble Alpes")
        information.addWidget(affiliation)

        email = QLabel(
            'Email: <a href="mailto:virgile.adam@ibs.fr">'
            'virgile.adam@ibs.fr</a>'
        )
        email.setOpenExternalLinks(True)
        email.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        information.addWidget(email)

        github = QLabel(
            '<a href="https://github.com/VirgileAdam/Percepta">'
            'GitHub / Percepta</a>'
        )
        github.setOpenExternalLinks(True)
        github.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        information.addWidget(github)

        content.addLayout(information, 1)
        outer.addLayout(content, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons, 0, Qt.AlignmentFlag.AlignRight)

        dialog.exec()

    def show_how_it_works(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("How Percepta works")
        dialog.resize(620, 470)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel("<h2>How Percepta hides an image in a pattern</h2>")
        title.setWordWrap(True)
        layout.addWidget(title)

        explanation = QLabel(
            """
            <p><b>1. The image is analysed locally.</b><br>
            Percepta looks at the brightness of the red, green and blue components
            in every small area of the source image.</p>

            <p><b>2. Brightness is converted into geometry.</b><br>
            Instead of drawing normal pixels, Percepta changes the width of stripes,
            the size of dots, or the thickness of a spiral. Bright areas contain more
            visible coloured material; dark areas contain less.</p>

            <p><b>3. The three colour channels are drawn separately.</b><br>
            Red, green and blue versions of the same pattern are slightly displaced.
            Where all three overlap, the result is white. Partial overlap produces
            cyan, magenta, yellow and coloured fringes.</p>

            <p><b>4. Distance reconstructs the picture.</b><br>
            From close up, the eye distinguishes the individual dots or lines.
            From farther away, these details become too small to resolve. The eye
            averages them together, much like the pixels of a screen, and the original
            image reappears.</p>

            <p><b>In one sentence:</b><br>
            Percepta preserves the average amount of red, green and blue light in each
            area, but redistributes that light into a visible geometric pattern.</p>
            """
        )
        explanation.setWordWrap(True)
        explanation.setTextFormat(Qt.TextFormat.RichText)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(6)
        content_layout.addWidget(explanation)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        hint = QLabel(
            "<b>Tip:</b> reduce the preview size, step back, or slightly squint "
            "to simulate the visual averaging."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        panel = QWidget()
        panel.setFixedWidth(280)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(5)

        image_box = QGroupBox("Image")
        image_layout = QVBoxLayout(image_box)
        image_layout.setContentsMargins(8, 6, 8, 6)
        image_layout.setSpacing(3)

        open_button = QPushButton("Open image…")
        open_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        open_button.clicked.connect(self.open_image)
        image_layout.addWidget(open_button)

        self.file_label = QLabel("No image loaded")
        self.file_label.setWordWrap(False)
        self.file_label.setMaximumHeight(24)
        image_layout.addWidget(self.file_label)
        panel_layout.addWidget(image_box)

        render_box = QGroupBox("Rendering")
        form = QFormLayout(render_box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(8, 6, 8, 6)
        form.setVerticalSpacing(3)

        self.pattern = QComboBox()
        self.pattern.addItems([
            "Vertical stripes",
            "Horizontal stripes",
            "Diagonal stripes",
            "Halftone",
            "Hexagonal halftone",
            "Spiral stripes"
        ])
        self.pattern.setCurrentIndex(0)
        form.addRow("Pattern", self.pattern)

        self.density = QSpinBox()
        self.density.setRange(4, 80)
        self.density.setValue(14)
        self.density_label = QLabel("Parameter")
        form.addRow(self.density_label, self.density)

        self.strength = QDoubleSpinBox()
        self.strength.setRange(0.10, 1.50)
        self.strength.setSingleStep(0.05)
        self.strength.setValue(0.80)
        form.addRow("Strength", self.strength)

        self.separation = QSpinBox()
        self.separation.setRange(0, 80)
        self.separation.setValue(10)
        self.separation.setSuffix(" px")
        form.addRow("Colour separation", self.separation)

        self.contrast = QDoubleSpinBox()
        self.contrast.setRange(0.30, 4.00)
        self.contrast.setSingleStep(0.10)
        self.contrast.setValue(1.55)
        form.addRow("Source contrast", self.contrast)

        self.output_size = QSpinBox()
        self.output_size.setRange(400, 4000)
        self.output_size.setSingleStep(100)
        self.output_size.setValue(1600)
        self.output_size.setSuffix(" px")
        form.addRow("Output size", self.output_size)
        panel_layout.addWidget(render_box)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        generate_button = QPushButton("Generate")
        generate_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        generate_button.clicked.connect(self.regenerate)
        buttons.addWidget(generate_button)

        self.export_button = QPushButton("Export…")
        self.export_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_button.clicked.connect(self.export_professional)
        self.export_button.setEnabled(False)
        buttons.addWidget(self.export_button)

        panel_layout.addLayout(buttons)
        framing_box = QGroupBox("Framing")
        framing_form = QFormLayout(framing_box)
        framing_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        framing_form.setContentsMargins(8, 6, 8, 6)
        framing_form.setVerticalSpacing(3)
        framing_form.setVerticalSpacing(4)
        self.crop_ratio = QComboBox()
        self.crop_ratio.addItems(["Square", "Portrait 4:5", "Landscape 4:3"])
        framing_form.addRow("Crop", self.crop_ratio)
        self.zoom = QDoubleSpinBox()
        self.zoom.setRange(1.0, 5.0)
        self.zoom.setSingleStep(0.05)
        self.zoom.setValue(1.0)
        framing_form.addRow("Zoom", self.zoom)
        self.pan_x = QSpinBox()
        self.pan_x.setRange(-100, 100)
        self.pan_x.setSuffix(" %")
        framing_form.addRow("Pan X", self.pan_x)
        self.pan_y = QSpinBox()
        self.pan_y.setRange(-100, 100)
        self.pan_y.setSuffix(" %")
        framing_form.addRow("Pan Y", self.pan_y)
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-180.0, 180.0)
        self.rotation.setSingleStep(1.0)
        self.rotation.setSuffix("°")
        framing_form.addRow("Rotation", self.rotation)
        reset_frame = QPushButton("Reset")
        reset_frame.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        reset_frame.clicked.connect(self.reset_framing)
        framing_form.addRow(reset_frame)

        self.lines_box = QGroupBox("Lines")
        lines_form = QFormLayout(self.lines_box)
        lines_form.setContentsMargins(8, 6, 8, 6)
        lines_form.setVerticalSpacing(3)
        self.line_smoothing = QSpinBox()
        self.line_smoothing.setRange(0, 30)
        self.line_smoothing.setValue(6)
        lines_form.addRow("Smoothing", self.line_smoothing)

        self.halftone_box = QGroupBox("Halftone")
        half_form = QFormLayout(self.halftone_box)
        half_form.setContentsMargins(8, 6, 8, 6)
        half_form.setVerticalSpacing(3)
        self.halftone_shape = QComboBox()
        self.halftone_shape.addItems(["Circle", "Square", "Diamond"])
        half_form.addRow("Dot shape", self.halftone_shape)
        self.halftone_angle = QDoubleSpinBox()
        self.halftone_angle.setRange(-90.0, 90.0)
        self.halftone_angle.setSuffix("°")
        half_form.addRow("Grid angle", self.halftone_angle)
        self.halftone_min = QDoubleSpinBox()
        self.halftone_min.setRange(0.0, 10.0)
        self.halftone_min.setValue(0.35)
        self.halftone_min.setSuffix(" px")
        half_form.addRow("Minimum dot", self.halftone_min)

        self.spiral_box = QGroupBox("Spiral")
        spiral_form = QFormLayout(self.spiral_box)
        spiral_form.setContentsMargins(8, 6, 8, 6)
        spiral_form.setVerticalSpacing(3)
        self.spiral_center_x = QDoubleSpinBox()
        self.spiral_center_x.setRange(0.0, 100.0)
        self.spiral_center_x.setValue(50.0)
        self.spiral_center_x.setSuffix(" %")
        spiral_form.addRow("Centre X", self.spiral_center_x)
        self.spiral_center_y = QDoubleSpinBox()
        self.spiral_center_y.setRange(0.0, 100.0)
        self.spiral_center_y.setValue(50.0)
        self.spiral_center_y.setSuffix(" %")
        spiral_form.addRow("Centre Y", self.spiral_center_y)
        self.spiral_clockwise = QCheckBox("Clockwise")
        self.spiral_clockwise.setChecked(True)
        spiral_form.addRow(self.spiral_clockwise)
        self.spiral_smoothing = QSpinBox()
        self.spiral_smoothing.setRange(1, 30)
        self.spiral_smoothing.setValue(6)
        spiral_form.addRow("Path smoothing", self.spiral_smoothing)


        options_tabs = QTabWidget()
        options_tabs.setDocumentMode(True)

        framing_tab = QWidget()
        framing_tab_layout = QVBoxLayout(framing_tab)
        framing_tab_layout.setContentsMargins(2, 2, 2, 2)
        framing_tab_layout.setSpacing(2)
        framing_tab_layout.addWidget(framing_box)
        framing_tab_layout.addStretch(1)
        options_tabs.addTab(framing_tab, "Framing")

        pattern_tab = QWidget()
        pattern_tab_layout = QVBoxLayout(pattern_tab)
        pattern_tab_layout.setContentsMargins(2, 2, 2, 2)
        pattern_tab_layout.setSpacing(2)
        pattern_tab_layout.addWidget(self.lines_box)
        pattern_tab_layout.addWidget(self.halftone_box)
        pattern_tab_layout.addWidget(self.spiral_box)
        pattern_tab_layout.addStretch(1)
        options_tabs.addTab(pattern_tab, "Pattern options")

        panel_layout.addWidget(options_tabs, 1)

        self.original = ImageView("Source image")
        self.output = ImageView("Generated pattern")

        previews = QWidget()
        previews_outer = QVBoxLayout(previews)
        previews_outer.setContentsMargins(0, 0, 0, 0)
        previews_outer.setSpacing(2)

        images_row = QHBoxLayout()
        images_row.setContentsMargins(0, 0, 0, 0)
        images_row.setSpacing(6)
        images_row.addWidget(self.original, 1)
        images_row.addWidget(self.output, 1)
        images_row.setStretch(0, 1)
        images_row.setStretch(1, 1)
        previews_outer.addLayout(images_row, 1)

        animation_row = QHBoxLayout()
        animation_row.setContentsMargins(0, 0, 0, 0)
        animation_row.setSpacing(4)
        animation_row.addWidget(QLabel("Parameter"))
        self.animation_start = QSpinBox()
        self.animation_start.setRange(4, 80)
        self.animation_start.setValue(4)
        self.animation_start.setFixedWidth(58)
        animation_row.addWidget(self.animation_start)
        animation_row.addWidget(QLabel("→"))
        self.animation_end = QSpinBox()
        self.animation_end.setRange(4, 80)
        self.animation_end.setValue(24)
        self.animation_end.setFixedWidth(58)
        animation_row.addWidget(self.animation_end)
        animation_row.addWidget(QLabel("Duration"))
        self.animation_duration = QDoubleSpinBox()
        self.animation_duration.setRange(0.5, 60.0)
        self.animation_duration.setValue(4.0)
        self.animation_duration.setSuffix(" s")
        self.animation_duration.setFixedWidth(68)
        animation_row.addWidget(self.animation_duration)
        animation_row.addWidget(QLabel("FPS"))
        self.animation_fps_box = QSpinBox()
        self.animation_fps_box.setRange(1, 60)
        self.animation_fps_box.setValue(12)
        self.animation_fps_box.setFixedWidth(52)
        animation_row.addWidget(self.animation_fps_box)
        self.animation_easing = QComboBox()
        self.animation_easing.addItems(["Linear", "Ease in", "Ease out", "Ease in-out"])
        self.animation_easing.setFixedWidth(86)
        animation_row.addWidget(self.animation_easing)
        self.animation_pingpong = QCheckBox("Ping-pong")
        animation_row.addWidget(self.animation_pingpong)
        animation_row.addStretch(1)
        self.make_animation_button = QPushButton("Create")
        self.make_animation_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.make_animation_button.clicked.connect(self.create_density_animation)
        animation_row.addWidget(self.make_animation_button)
        animation_box = QWidget()
        animation_box_layout = QVBoxLayout(animation_box)
        animation_box_layout.setContentsMargins(0, 0, 0, 0)
        animation_box_layout.setSpacing(2)
        animation_box_layout.addLayout(animation_row)

        playback_row = QHBoxLayout()
        playback_row.setContentsMargins(0, 0, 0, 0)
        playback_row.setSpacing(4)
        self.play_pause_button = QPushButton("Play/Pause")
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_pause_button.clicked.connect(self.toggle_animation)
        self.play_pause_button.setEnabled(False)
        playback_row.addWidget(self.play_pause_button)
        self.stop_animation_button = QPushButton("Stop")
        self.stop_animation_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_animation_button.clicked.connect(self.stop_animation)
        self.stop_animation_button.setEnabled(False)
        playback_row.addWidget(self.stop_animation_button)
        self.animation_slider = QSlider(Qt.Orientation.Horizontal)
        self.animation_slider.setRange(0, 0)
        self.animation_slider.valueChanged.connect(self.seek_animation)
        playback_row.addWidget(self.animation_slider, 1)
        self.save_animation_button = QPushButton("Save")
        self.save_animation_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_animation_button.clicked.connect(self.save_density_animation)
        self.save_animation_button.setEnabled(False)
        playback_row.addWidget(self.save_animation_button)
        animation_box_layout.addLayout(playback_row)
        previews_outer.addWidget(animation_box)

        layout.addWidget(panel)
        layout.addWidget(previews, 1)
        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
        root.setMaximumWidth(1125)
        
        self.pattern.currentTextChanged.connect(self.update_pattern_controls)
        self.pattern.currentTextChanged.connect(self.apply_density_profile)
        self.pattern.currentTextChanged.connect(self.schedule)
        for widget in (
            self.density, self.strength, self.separation, self.contrast,
            self.zoom, self.pan_x, self.pan_y, self.rotation,
            self.line_smoothing, self.halftone_angle, self.halftone_min,
            self.spiral_center_x, self.spiral_center_y, self.spiral_smoothing
        ):
            widget.valueChanged.connect(self.schedule)
        self.output_size.valueChanged.connect(self.update_density_for_output_size)
        self.output_size.valueChanged.connect(self.schedule)
        self.crop_ratio.currentTextChanged.connect(self.schedule)
        self.halftone_shape.currentTextChanged.connect(self.schedule)
        self.spiral_clockwise.toggled.connect(self.schedule)
        self.update_pattern_controls()
        self.apply_density_profile(self.pattern.currentText())

    def renderer_density_from_value(self, value: int, pattern: str | None = None) -> int:
        """Convert the visible pattern parameter to the value expected by the renderer."""
        pattern = pattern or self.pattern.currentText()
        value = int(value)

        if pattern in ("Vertical stripes", "Horizontal stripes", "Diagonal stripes"):
                                                                     
            return max(1, value)

        if pattern in ("Halftone", "Hexagonal halftone"):
                                                                                
            return max(1, value)

        if pattern == "Spiral stripes":
                                                                              
            return max(1, round(216 / max(1, value)))

        return max(1, value)

    def renderer_density_value(self) -> int:
        """Return the current visible parameter converted for the active renderer."""
        return self.renderer_density_from_value(
            self.density.value(),
            self.pattern.currentText()
        )

    def settings(self) -> Settings:
        return Settings(
            pattern=self.pattern.currentText(),
            density=self.renderer_density_value(),
            strength=self.strength.value(),
            colour_separation=self.separation.value(),
            contrast=self.contrast.value(),
            output_size=self.output_size.value(),
            zoom=self.zoom.value(),
            pan_x=self.pan_x.value(),
            pan_y=self.pan_y.value(),
            rotation=self.rotation.value(),
            crop_ratio=self.crop_ratio.currentText(),
            line_smoothing=self.line_smoothing.value(),
            halftone_shape=self.halftone_shape.currentText(),
            halftone_angle=self.halftone_angle.value(),
            halftone_min_size=self.halftone_min.value(),
            spiral_center_x=self.spiral_center_x.value(),
            spiral_center_y=self.spiral_center_y.value(),
            spiral_clockwise=self.spiral_clockwise.isChecked(),
            spiral_smoothing=self.spiral_smoothing.value()
        )

    def scaled_pattern_value(self, base_value: int) -> int:
        scale = self.output_size.value() / REFERENCE_OUTPUT_SIZE
        return max(1, int(round(base_value * scale)))

    def update_density_for_output_size(self):
        self.apply_density_profile(self.pattern.currentText())

    def apply_density_profile(self, pattern: str, preserve_relative: bool = False):
        """Adapt the shared control to the real geometric parameter of each pattern."""
        profile = PATTERN_PARAMETER_PROFILES.get(
            pattern,
            PATTERN_PARAMETER_PROFILES["Vertical stripes"]
        )

        old_min = self.density.minimum()
        old_max = self.density.maximum()
        old_value = self.density.value()

        controls = (self.density, self.animation_start, self.animation_end)
        for control in controls:
            control.blockSignals(True)

        try:
            scaled_minimum = self.scaled_pattern_value(profile["minimum"])
            scaled_maximum = self.scaled_pattern_value(profile["maximum"])
            scaled_default = self.scaled_pattern_value(profile["default"])
            scaled_start = self.scaled_pattern_value(profile["animation_start"])
            scaled_end = self.scaled_pattern_value(profile["animation_end"])

            self.density.setRange(scaled_minimum, scaled_maximum)
            self.animation_start.setRange(scaled_minimum, scaled_maximum)
            self.animation_end.setRange(scaled_minimum, scaled_maximum)

            suffix = profile.get("suffix", "")
            self.density.setSuffix(suffix)
            self.animation_start.setSuffix(suffix)
            self.animation_end.setSuffix(suffix)

            if preserve_relative and old_max > old_min:
                fraction = (old_value - old_min) / (old_max - old_min)
                value = round(
                    profile["minimum"]
                    + fraction * (profile["maximum"] - profile["minimum"])
                )
            else:
                value = scaled_default

            value = max(scaled_minimum, min(scaled_maximum, value))
            self.density.setValue(value)
            self.animation_start.setValue(scaled_start)
            self.animation_end.setValue(scaled_end)

            self.density_label.setText(profile["label"])
            if hasattr(self, "animation_parameter_label"):
                self.animation_parameter_label.setText(profile["label"])
            scale_note = (
                f" Adapted automatically for a {self.output_size.value()} px output "
                f"(reference: {REFERENCE_OUTPUT_SIZE} px)."
            )
            self.density.setToolTip(profile["tooltip"] + scale_note)
            self.animation_start.setToolTip(
                "Animation start — " + profile["tooltip"]
            )
            self.animation_end.setToolTip(
                "Animation end — " + profile["tooltip"]
            )
        finally:
            for control in controls:
                control.blockSignals(False)

        self.schedule()

    def update_pattern_controls(self):
        pattern = self.pattern.currentText()
        self.lines_box.setVisible("stripes" in pattern.lower() and "spiral" not in pattern.lower())
        self.halftone_box.setVisible("halftone" in pattern.lower())
        self.spiral_box.setVisible("spiral" in pattern.lower())

    def reset_framing(self):
        self.crop_ratio.setCurrentText("Square")
        self.zoom.setValue(1.0)
        self.pan_x.setValue(0)
        self.pan_y.setValue(0)
        self.rotation.setValue(0.0)

    def schedule(self):
        if self.source is not None:
            self.timer.start(160)

    def open_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;All files (*)"
        )
        if filename:
            self.load_path(Path(filename))

    def load_path(self, path: Path):
        try:
            image = Image.open(path)
            image.load()
            self.source = ImageOps.exif_transpose(image).convert("RGB")
            self.path = path
            self.animation_frames.clear()
            self.playback_timer.stop()
            self.save_animation_button.setEnabled(False)
            self.play_pause_button.setEnabled(False)
            self.stop_animation_button.setEnabled(False)
            self.file_label.setText(path.name)
            self.original.set_image(framed_source(self.source, self.settings()))
            self.regenerate()
        except Exception as exc:
            QMessageBox.critical(self, "Unable to open image", str(exc))

    def regenerate(self):
        if self.source is None:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            current = self.settings()
            self.original.set_image(framed_source(self.source, current))
            self.result, used = generate(self.source, current)
            self.output.set_image(self.result)
            self.export_button.setEnabled(True)
            self.statusBar().showMessage(
                f"Pattern: {used} — {self.result.width} × {self.result.height} px",
                5000
            )
        except Exception as exc:
            QMessageBox.critical(self, "Generation error", f"{type(exc).__name__}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def _ease(self, t: float) -> float:
        mode = self.animation_easing.currentText()
        if mode == "Ease in":
            return t*t
        if mode == "Ease out":
            return 1-(1-t)*(1-t)
        if mode == "Ease in-out":
            return 3*t*t-2*t*t*t
        return t

    def create_density_animation(self):
        if self.source is None:
            QMessageBox.information(self, "No image", "Open an image first.")
            return
        start, end = self.animation_start.value(), self.animation_end.value()
        fps = self.animation_fps_box.value()
        frame_count = max(2, int(round(self.animation_duration.value()*fps)))
        densities = [
            int(round(start + (end-start)*self._ease(i/(frame_count-1))))
            for i in range(frame_count)
        ]
        if self.animation_pingpong.isChecked():
            densities += densities[-2:0:-1]

        progress = QProgressDialog(
            "Generating animation frames…", "Cancel", 0, len(densities), self
        )
        progress.setWindowTitle("Density animation")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        frames = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            base = self.settings()
            for i, density in enumerate(densities):
                progress.setValue(i)
                QApplication.processEvents()
                if progress.wasCanceled():
                    frames = []
                    break
                s = Settings(**{**base.__dict__, "density": density})
                frame, _ = generate(self.source, s)
                frames.append(frame)
            progress.setValue(len(densities))
        except Exception as exc:
            QMessageBox.critical(self, "Animation error", str(exc))
            frames = []
        finally:
            QApplication.restoreOverrideCursor()

        if not frames:
            return
        self.animation_frames = frames
        self.animation_index = 0
        self.animation_fps = fps
        self.animation_delay_ms = max(1, int(round(1000/fps)))
        self.animation_slider.setRange(0, len(frames)-1)
        self.animation_slider.setValue(0)
        self.play_pause_button.setEnabled(True)
        self.stop_animation_button.setEnabled(True)
        self.save_animation_button.setEnabled(True)
        self.output.set_image(frames[0])
        self.playback_timer.start(self.animation_delay_ms)

    def show_next_animation_frame(self):
        if not self.animation_frames:
            self.playback_timer.stop()
            return
        self.animation_index = (self.animation_index + 1) % len(self.animation_frames)
        self.animation_slider.blockSignals(True)
        self.animation_slider.setValue(self.animation_index)
        self.animation_slider.blockSignals(False)
        self.output.set_image(self.animation_frames[self.animation_index])

    def toggle_animation(self):
        if not self.animation_frames:
            return
        if self.playback_timer.isActive():
            self.playback_timer.stop()
        else:
            self.playback_timer.start(self.animation_delay_ms)

    def stop_animation(self):
        self.playback_timer.stop()
        if self.animation_frames:
            self.animation_index = 0
            self.animation_slider.setValue(0)
            self.output.set_image(self.animation_frames[0])

    def seek_animation(self, index: int):
        if not self.animation_frames:
            return
        self.animation_index = max(0, min(index, len(self.animation_frames)-1))
        self.output.set_image(self.animation_frames[self.animation_index])

    def save_density_animation(self):
        if not self.animation_frames:
            return
        stem = self.path.stem if self.path else "illusion"
        filename, selected = QFileDialog.getSaveFileName(
            self, "Save animation", f"{stem}_density_animation.mp4",
            "MP4 video (*.mp4);;WebM video (*.webm);;Animated GIF (*.gif)"
        )
        if not filename:
            return
        ext = Path(filename).suffix.lower()
        if not ext:
            ext = ".gif" if "GIF" in selected else ".webm" if "WebM" in selected else ".mp4"
            filename += ext
        try:
            arrays = [np.asarray(frame.convert("RGB"), dtype=np.uint8) for frame in self.animation_frames]
            if ext == ".gif":
                first, *rest = self.animation_frames
                first.save(
                    filename, save_all=True, append_images=rest,
                    duration=self.animation_delay_ms, loop=0,
                    optimize=False, disposal=2
                )
            else:
                try:
                    import imageio.v3 as iio
                except ImportError as exc:
                    raise RuntimeError(
                        "MP4/WebM export requires imageio and imageio-ffmpeg. "
                        "Install requirements.txt."
                    ) from exc
                codec = "libvpx-vp9" if ext == ".webm" else "libx264"
                iio.imwrite(filename, np.stack(arrays), fps=self.animation_fps, codec=codec)
            self.statusBar().showMessage(f"Animation saved: {Path(filename).name}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Animation export error", str(exc))

    def export_professional(self):
        if self.result is None:
            return
        dialog = ExportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        fmt = dialog.format.currentText()
        filters = {
            "PNG": "PNG image (*.png)", "TIFF": "TIFF image (*.tif *.tiff)",
            "PDF": "PDF document (*.pdf)", "SVG": "SVG image (*.svg)"
        }
        stem = self.path.stem if self.path else "illusion"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export", f"{stem}_illusion.{fmt.lower()}", filters[fmt]
        )
        if not filename:
            return
        ext_map = {"PNG": ".png", "TIFF": ".tif", "PDF": ".pdf", "SVG": ".svg"}
        if not Path(filename).suffix:
            filename += ext_map[fmt]

        dpi = dialog.dpi.value()
        target_px = max(64, int(round(dialog.width_cm.value()/2.54*dpi)))
        image = self.result.resize((target_px, target_px), Image.Resampling.LANCZOS)
        bg = dialog.background.currentText()
        if bg == "Transparent":
            rgba = image.convert("RGBA")
            arr = np.asarray(rgba).copy()
            arr[..., 3] = np.max(arr[..., :3], axis=2)
            image = Image.fromarray(arr, "RGBA")
        elif bg == "White":
            white = Image.new("RGB", image.size, "white")
            mask = Image.fromarray(np.max(np.asarray(image), axis=2).astype(np.uint8))
            white.paste(image, mask=mask)
            image = white
        bleed_px = int(round(dialog.bleed.value()/25.4*dpi))
        if bleed_px:
            fill = (255,255,255,0) if bg == "Transparent" else ("white" if bg == "White" else "black")
            image = ImageOps.expand(image, border=bleed_px, fill=fill)

        try:
            if fmt == "PNG":
                image.save(filename, dpi=(dpi, dpi))
            elif fmt == "TIFF":
                image.save(filename, compression="tiff_lzw", dpi=(dpi, dpi))
            elif fmt == "PDF":
                image.convert("RGB").save(filename, "PDF", resolution=dpi)
            else:
                buffer = io.BytesIO()
                image.convert("RGBA").save(buffer, "PNG")
                payload = base64.b64encode(buffer.getvalue()).decode("ascii")
                w, h = image.size
                svg = (
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'viewBox="0 0 {w} {h}"><image width="{w}" height="{h}" '
                    f'href="data:image/png;base64,{payload}"/></svg>'
                )
                Path(filename).write_text(svg, encoding="utf-8")
            self.statusBar().showMessage(f"Exported: {Path(filename).name}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))

    def export_png(self):
        if self.result is None:
            return

        stem = self.path.stem if self.path else "illusion"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", f"{stem}_illusion.png", "PNG image (*.png)"
        )
        if filename:
            if not filename.lower().endswith(".png"):
                filename += ".png"
            try:
                self.result.save(filename, "PNG", optimize=True)
            except Exception as exc:
                QMessageBox.critical(self, "Export error", str(exc))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.load_path(Path(urls[0].toLocalFile()))


def main():
    set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Percepta")
    app.setApplicationDisplayName("Percepta")
    app.setOrganizationName("Virgile ADAM")
    app.setStyle("Fusion")

    icon_path = resource_path("assets/percepta.ico")
    if not icon_path.exists():
        icon_path = resource_path("assets/percepta_icon.png")

    icon = QIcon(str(icon_path))
    app.setWindowIcon(icon)

    splash_pixmap = QPixmap(str(resource_path("assets/percepta_splash.png")))
    splash = QSplashScreen(splash_pixmap)
    splash.setWindowIcon(icon)
    splash.show()
    splash.raise_()
    splash.activateWindow()
    app.processEvents()

    splash_started = time.monotonic()
    minimum_splash_seconds = 1.8

    window = MainWindow()
    window.setWindowIcon(icon)

    elapsed = time.monotonic() - splash_started
    remaining_ms = max(0, int((minimum_splash_seconds - elapsed) * 1000))

    def reveal_main_window():
        window.show()
        window.raise_()
        window.activateWindow()
        splash.finish(window)

    QTimer.singleShot(remaining_ms, reveal_main_window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
