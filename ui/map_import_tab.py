"""Map Import tab -- loads GeoJSON/TAB boundaries, rasterizes, and previews.

Provides a self-contained workflow for importing GIS boundary data
(GeoJSON, MapInfo TAB) and converting it to a raster boundary image
usable by the territory/province generation pipeline.
"""

import json
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFileDialog, QMessageBox,
    QGroupBox, QLineEdit,
)

from logic.geojson_importer import (
    _compute_bounds, _lonlat_to_pixel, _parse_feature_geometries,
)
from ui.image_display import ImageDisplay

# Field names to try when extracting region names from properties
_NAME_FIELDS = ("lga_name", "LGA_NAME", "name", "NAME", "abb_name", "ABB_NAME")


class MapImportTab(QWidget):
    """Tab for importing GIS map data (GeoJSON boundaries -> raster)."""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self._sources = []          # list of (filename, features) tuples
        self._combined_features = []  # cached flattened feature list
        self._bbox = None           # union bbox of all sources
        self._rasterized_image = None

        layout = QVBoxLayout(self)

        # ---- Row 0: Load GeoJSON ----
        load_group = QGroupBox("GeoJSON Source")
        load_layout = QVBoxLayout(load_group)
        layout.addWidget(load_group)

        load_btn_row = QHBoxLayout()
        load_layout.addLayout(load_btn_row)

        self._btn_load = QPushButton("Load Boundaries...")
        self._btn_load.setToolTip(
            "Select one or more .tab / .geojson boundary files.\n"
            "Replaces all currently loaded boundaries."
        )
        self._btn_load.clicked.connect(self._on_load)
        load_btn_row.addWidget(self._btn_load)

        self._btn_add = QPushButton("Add Boundaries...")
        self._btn_add.setToolTip(
            "Append additional boundary files to the current set.\n"
            "All boundaries will be combined into a single raster."
        )
        self._btn_add.clicked.connect(self._on_add)
        self._btn_add.setEnabled(False)
        load_btn_row.addWidget(self._btn_add)

        self._lbl_file = QLineEdit()
        self._lbl_file.setReadOnly(True)
        self._lbl_file.setPlaceholderText("No files loaded")
        load_btn_row.addWidget(self._lbl_file, stretch=1)

        self._lbl_info = QLabel("")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet("color: #9d9d9d; font-size: 11px;")
        load_layout.addWidget(self._lbl_info)

        # ---- Row 1: Raster settings ----
        raster_group = QGroupBox("Rasterization Settings")
        raster_layout = QHBoxLayout(raster_group)
        layout.addWidget(raster_group)

        raster_layout.addWidget(QLabel("Width:"))
        self._spin_width = QSpinBox()
        self._spin_width.setRange(100, 20000)
        self._spin_width.setValue(2000)
        self._spin_width.setSingleStep(100)
        raster_layout.addWidget(self._spin_width)

        raster_layout.addWidget(QLabel("Line:"))
        self._spin_line = QSpinBox()
        self._spin_line.setRange(1, 10)
        self._spin_line.setValue(2)
        raster_layout.addWidget(self._spin_line)

        self._btn_rasterize = QPushButton("Rasterize")
        self._btn_rasterize.clicked.connect(self._on_rasterize)
        self._btn_rasterize.setEnabled(False)
        raster_layout.addWidget(self._btn_rasterize)

        self._btn_land = QPushButton("Generate Land Image")
        self._btn_land.clicked.connect(self._on_generate_land)
        self._btn_land.setEnabled(False)
        self._btn_land.setToolTip(
            "Generate a land/sea image from Natural Earth coastline data\n"
            "matching the boundary image dimensions and geographic bounds."
        )
        raster_layout.addWidget(self._btn_land)

        from PyQt6.QtWidgets import QCheckBox
        self._chk_clip = QCheckBox("Clip to Land")
        self._chk_clip.setChecked(True)
        self._chk_clip.setToolTip(
            "Clip boundary polygons to the coastline so they don't extend\n"
            "into the ocean. Prevents artificial sea borders."
        )
        raster_layout.addWidget(self._chk_clip)

        raster_layout.addStretch()

        # ---- Row 2: Preview ----
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        layout.addWidget(preview_group, stretch=1)

        self._preview = ImageDisplay()
        preview_layout.addWidget(self._preview)

        # ---- Row 3: Actions ----
        action_row = QHBoxLayout()
        layout.addLayout(action_row)

        self._btn_send = QPushButton("Send to Boundary Tab")
        self._btn_send.clicked.connect(self._on_send_to_boundary)
        self._btn_send.setEnabled(False)
        action_row.addWidget(self._btn_send)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_clear.setEnabled(False)
        action_row.addWidget(self._btn_clear)

        action_row.addStretch()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_load(self):
        """Load boundary files, replacing all current sources."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Boundary Data", "",
            "All Supported (*.geojson *.json *.tab);;"
            "GeoJSON (*.geojson *.json);;"
            "MapInfo TAB (*.tab);;"
            "All Files (*)"
        )
        if not paths:
            return

        self._sources = []
        for path in paths:
            source = self._load_file(path)
            if source is not None:
                self._sources.append(source)

        if not self._sources:
            return

        self._rebuild_combined()
        self._update_ui_after_load()

    def _on_add(self):
        """Append additional boundary files to current sources."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Boundary Data", "",
            "All Supported (*.geojson *.json *.tab);;"
            "GeoJSON (*.geojson *.json);;"
            "MapInfo TAB (*.tab);;"
            "All Files (*)"
        )
        if not paths:
            return

        added = 0
        for path in paths:
            source = self._load_file(path)
            if source is not None:
                self._sources.append(source)
                added += 1

        if added == 0:
            return

        self._rebuild_combined()
        self._update_ui_after_load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_file(self, path):
        """Load a single boundary file. Returns (filename, features) or None."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".tab":
            path = self._convert_tab_to_geojson(path)
            if path is None:
                return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.critical(self, "Load Error", f"{os.path.basename(path)}:\n{e}")
            return None

        if data.get("type") == "FeatureCollection":
            features = data.get("features", [])
        elif data.get("type") == "Feature":
            features = [data]
        else:
            QMessageBox.critical(
                self, "Load Error",
                f"{os.path.basename(path)}: expected FeatureCollection, "
                f"got {data.get('type')}"
            )
            return None

        if not features:
            QMessageBox.critical(
                self, "Load Error",
                f"{os.path.basename(path)}: no features found."
            )
            return None

        return (path, features)

    def _rebuild_combined(self):
        """Flatten all sources into one feature list and recompute union bbox."""
        all_features = []
        for _path, feats in self._sources:
            all_features.extend(feats)
        self._combined_features = all_features
        if all_features:
            self._bbox = _compute_bounds(all_features)
        else:
            self._bbox = None

    def _detect_region_name(self):
        """Derive a human-readable region name from the loaded boundary data.

        Checks the 'state' property across all features.  If all features
        share the same state code, the full state name is returned.
        Otherwise "Australia" is used as the fallback for multi-state data.
        """
        _STATE_NAMES = {
            "WA":  "Western Australia",
            "NSW": "New South Wales",
            "VIC": "Victoria",
            "QLD": "Queensland",
            "SA":  "South Australia",
            "TAS": "Tasmania",
            "NT":  "Northern Territory",
            "ACT": "Australian Capital Territory",
            "OT":  "Other Territories",
        }
        states = set()
        for feat in self._combined_features:
            props = feat.get("properties") or {}
            # Both 'state' (TAB) and 'STATE' (SHP) are used
            s = props.get("state") or props.get("STATE") or ""
            if s:
                states.add(s.upper())
        if len(states) == 1:
            code = states.pop()
            return _STATE_NAMES.get(code, code)
        return "Australia"

    def _render_dir(self):
        """Ensure the renders/ directory exists and return its path."""
        d = os.path.join(os.path.dirname(os.path.dirname(__file__)), "renders")
        os.makedirs(d, exist_ok=True)
        return d

    def _update_ui_after_load(self):
        """Update UI labels and enable buttons after loading."""
        total_features = len(self._combined_features)

        # Count unique region names
        names = set()
        for feat in self._combined_features:
            props = feat.get("properties", {})
            for field in _NAME_FIELDS:
                val = props.get(field)
                if val:
                    names.add(str(val))
                    break

        # File label
        if len(self._sources) == 1:
            self._lbl_file.setText(self._sources[0][0])
        else:
            self._lbl_file.setText(f"{len(self._sources)} files loaded")

        # Info label
        min_lon, min_lat, max_lon, max_lat = self._bbox
        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat
        aspect = lon_span / lat_span if lat_span > 0 else 1.0

        self._lbl_info.setText(
            f"Sources: {len(self._sources)}  |  "
            f"Features: {total_features}  |  "
            f"Regions: {len(names) if names else 'N/A'}  |  "
            f"Bounds: lon {min_lon:.2f}..{max_lon:.2f}, "
            f"lat {min_lat:.2f}..{max_lat:.2f}  |  "
            f"Aspect: {aspect:.2f}"
        )

        # Default width
        if aspect >= 1.0:
            self._spin_width.setValue(2000)
        else:
            self._spin_width.setValue(max(100, int(2000 * aspect)))

        # Enable buttons
        self._btn_rasterize.setEnabled(True)
        self._btn_land.setEnabled(True)
        self._btn_send.setEnabled(False)
        self._btn_clear.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._rasterized_image = None
        self._preview.set_image(None)

        # Auto-rasterize
        self._on_rasterize()

    def _on_rasterize(self):
        features = self._combined_features
        if not features or self._bbox is None:
            return

        # If clipping is enabled, pre-clip features to land polygon
        if self._chk_clip.isChecked():
            land_geom = self._get_land_polygon()
            features = self._clip_features_to_land(features, land_geom)

        img_w = self._spin_width.value()
        line_w = self._spin_line.value()

        lon_span = self._bbox[2] - self._bbox[0]
        lat_span = self._bbox[3] - self._bbox[1]
        aspect = lon_span / lat_span if lat_span > 0 else 1.0
        img_h = max(1, int(img_w / aspect)) if aspect > 0 else img_w

        img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)

        drawn = 0
        for feature in features:
            for ring in _parse_feature_geometries(feature):
                if len(ring) < 2:
                    continue
                pixels = [
                    _lonlat_to_pixel(lon, lat, self._bbox, img_w, img_h)
                    for lon, lat in ring
                ]
                for i in range(len(pixels) - 1):
                    draw.line(
                        [pixels[i], pixels[i + 1]],
                        fill=(0, 0, 0, 255), width=line_w
                    )
                drawn += 1

        self._rasterized_image = img
        self._preview.set_image(img)
        self._btn_send.setEnabled(True)

        # Auto-save to renders/
        name = self._detect_region_name().replace(" ", "_")
        out = os.path.join(self._render_dir(), f"{name}_boundary.png")
        img.save(out)

    def _on_send_to_boundary(self):
        if self._rasterized_image is None:
            return
        self._main.boundary_image_display.set_image(self._rasterized_image)
        self._main.check_territory_ready()
        # Switch to Boundary tab so user can see the result
        for i in range(self._main.tabs.count()):
            if self._main.tabs.tabText(i) == "Boundary Image":
                self._main.tabs.setCurrentIndex(i)
                break
        QMessageBox.information(
            self, "Sent",
            "Rasterized boundary image sent to the Boundary Image tab."
        )

    def _on_clear(self):
        self._sources = []
        self._combined_features = []
        self._bbox = None
        self._rasterized_image = None
        self._lbl_file.clear()
        self._lbl_info.setText("")
        self._preview.set_image(None)
        self._btn_rasterize.setEnabled(False)
        self._btn_land.setEnabled(False)
        self._btn_send.setEnabled(False)
        self._btn_clear.setEnabled(False)
        self._btn_add.setEnabled(False)

    def _on_generate_land(self):
        """Generate a land/sea image from coastline data."""
        if not self._combined_features or self._bbox is None:
            return

        # Use rasterized image dimensions, or compute from bbox + spin width
        if self._rasterized_image is not None:
            img_w, img_h = self._rasterized_image.size
        else:
            img_w = self._spin_width.value()
            lon_span = self._bbox[2] - self._bbox[0]
            lat_span = self._bbox[3] - self._bbox[1]
            aspect = lon_span / lat_span if lat_span > 0 else 1.0
            img_h = max(1, int(img_w / aspect)) if aspect > 0 else img_w

        try:
            from logic.land_generator import generate_land_image
            land_img = generate_land_image(self._bbox, img_w, img_h)
        except Exception as e:
            QMessageBox.critical(
                self, "Land Generation Error",
                f"Failed to generate land image:\n{e}"
            )
            return

        # Set on the Land Image tab
        self._main.land_image_display.set_image(land_img)
        self._main.check_territory_ready()

        # Auto-save to renders/
        name = self._detect_region_name().replace(" ", "_")
        out = os.path.join(self._render_dir(), f"{name}_land.png")
        land_img.save(out)

        QMessageBox.information(
            self, "Land Image Generated",
            f"Land/sea image generated at {land_img.width}x{land_img.height} px.\n"
            "Ocean = dark green (5,20,18), Land = white.\n"
            f"Saved to renders/{name}_land.png"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_land_polygon(self):
        """Return a shapely Polygon/MultiPolygon of land for the current bbox.

        Uses cartopy's Natural Earth land data, clipped to the bbox.
        Result is cached for the lifetime of the current bbox.
        """
        import cartopy.feature as cfeature
        from shapely.geometry import box
        from shapely.ops import unary_union

        min_lon, min_lat, max_lon, max_lat = self._bbox
        pad = 0.05
        clip_box = box(
            min_lon - (max_lon - min_lon) * pad,
            min_lat - (max_lat - min_lat) * pad,
            max_lon + (max_lon - min_lon) * pad,
            max_lat + (max_lat - min_lat) * pad,
        )
        land_union = unary_union([
            g for g in cfeature.LAND.with_scale("10m").geometries()
            if g is not None and not g.is_empty
        ])
        return land_union.intersection(clip_box)

    def _clip_features_to_land(self, features, land_geom):
        """Clip GeoJSON features to land polygon, keeping only boundary segments
        that intersect land.

        Returns a new list of features whose geometry coordinates have been
        clipped.  Segments entirely in the ocean are dropped.
        """
        from shapely.geometry import LineString, shape

        if land_geom is None or land_geom.is_empty:
            return features

        clipped = []
        for feat in features:
            geom = feat.get("geometry")
            if geom is None:
                clipped.append(feat)
                continue

            geom_type = geom["type"]
            try:
                if geom_type == "Polygon":
                    rings = geom["coordinates"]
                    new_rings = []
                    for ring in rings:
                        if len(ring) < 2:
                            continue
                        line = LineString(ring)
                        inter = line.intersection(land_geom)
                        if inter.is_empty:
                            continue
                        for seg in (inter.geoms if inter.geom_type == "MultiLineString" else [inter]):
                            if seg.geom_type == "LineString" and len(seg.coords) >= 2:
                                new_rings.append(list(seg.coords))
                            elif seg.geom_type == "MultiLineString":
                                for sub in seg.geoms:
                                    if sub.geom_type == "LineString" and len(sub.coords) >= 2:
                                        new_rings.append(list(sub.coords))
                    if new_rings:
                        new_feat = dict(feat)
                        new_feat["geometry"] = {"type": "Polygon", "coordinates": new_rings}
                        clipped.append(new_feat)

                elif geom_type == "MultiPolygon":
                    new_polys = []
                    for poly_coords in geom["coordinates"]:
                        new_rings = []
                        for ring in poly_coords:
                            if len(ring) < 2:
                                continue
                            line = LineString(ring)
                            inter = line.intersection(land_geom)
                            if inter.is_empty:
                                continue
                            for seg in (inter.geoms if inter.geom_type == "MultiLineString" else [inter]):
                                if seg.geom_type == "LineString" and len(seg.coords) >= 2:
                                    new_rings.append(list(seg.coords))
                                elif seg.geom_type == "MultiLineString":
                                    for sub in seg.geoms:
                                        if sub.geom_type == "LineString" and len(sub.coords) >= 2:
                                            new_rings.append(list(sub.coords))
                        if new_rings:
                            new_polys.append(new_rings)
                    if new_polys:
                        new_feat = dict(feat)
                        new_feat["geometry"] = {"type": "MultiPolygon", "coordinates": new_polys}
                        clipped.append(new_feat)

                else:
                    clipped.append(feat)
            except Exception:
                clipped.append(feat)

        return clipped

    def _convert_tab_to_geojson(self, tab_path):
        """Convert a MapInfo TAB file to a temporary GeoJSON via ogr2ogr.

        Returns the path to the temporary GeoJSON file, or None on failure.
        """
        tmpdir = tempfile.mkdtemp(prefix="ogs_mt_")
        tmp_path = os.path.join(tmpdir, "boundary.geojson")
        try:
            proc = subprocess.run(
                ["ogr2ogr", "-f", "GeoJSON", tmp_path, tab_path],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                QMessageBox.critical(
                    self, "Conversion Error",
                    f"Failed to convert TAB to GeoJSON:\n{stderr}"
                )
                return None
        except FileNotFoundError:
            QMessageBox.critical(
                self, "Missing Tool",
                "ogr2ogr (GDAL) is required to read MapInfo TAB files.\n"
                "Install it with: sudo apt install gdal-bin"
            )
            return None
        except subprocess.TimeoutExpired:
            QMessageBox.critical(
                self, "Conversion Error",
                "TAB to GeoJSON conversion timed out. File may be too large."
            )
            return None

        # Verify the output is valid JSON
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.critical(self, "Conversion Error", str(e))
            return None

        return tmp_path
