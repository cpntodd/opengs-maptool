"""GeoJSON-to-boundary-image importer.

Reads a GeoJSON FeatureCollection containing Polygon or MultiPolygon features
and rasterizes their outlines onto a PIL Image suitable for the tool's
Boundary Image tab. The image uses black (0,0,0) for boundary lines on a white
background, matching the format expected by extract_masks().
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _parse_feature_geometries(feature):
    """Yield individual polygon coordinate rings from a GeoJSON feature.

    Handles Polygon, MultiPolygon, and GeometryCollection.
    Each yielded item is a list of (x, y) pixel coordinate tuples.
    """
    geom = feature.get("geometry")
    if geom is None:
        return

    geom_type = geom["type"]
    coords = geom["coordinates"]

    if geom_type == "Polygon":
        # coords[0] is outer ring, remaining are holes
        for ring in coords:
            yield [(pt[0], pt[1]) for pt in ring]

    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                yield [(pt[0], pt[1]) for pt in ring]

    elif geom_type == "GeometryCollection":
        for sub_geom in geom.get("geometries", []):
            sub = {"type": "Feature", "geometry": sub_geom, "properties": {}}
            yield from _parse_feature_geometries(sub)


def _compute_bounds(features):
    """Compute the geographic bounding box of all features.

    Returns (min_lon, min_lat, max_lon, max_lat).
    """
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")

    for feature in features:
        for ring in _parse_feature_geometries(feature):
            for x, y in ring:
                if x < min_lon:
                    min_lon = x
                if x > max_lon:
                    max_lon = x
                if y < min_lat:
                    min_lat = y
                if y > max_lat:
                    max_lat = y

    return min_lon, min_lat, max_lon, max_lat


def _lonlat_to_pixel(lon, lat, bbox, img_w, img_h, pad_pct=0.05):
    """Convert geographic lon/lat to pixel coordinates.

    Applies padding (pad_pct) around the bounding box so boundaries don't
    touch the image edge. Latitudes are flipped because image Y=0 is top,
    while latitudes increase northward.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    lon_range = max_lon - min_lon
    lat_range = max_lat - min_lat

    if lon_range < 0.001:
        lon_range = 0.001
    if lat_range < 0.001:
        lat_range = 0.001

    pad_x = lon_range * pad_pct
    pad_y = lat_range * pad_pct

    effective_w = img_w / (1 + 2 * pad_pct)
    effective_h = img_h / (1 + 2 * pad_pct)
    offset_x = img_w * pad_pct / (1 + 2 * pad_pct)
    offset_y = img_h * pad_pct / (1 + 2 * pad_pct)

    px = offset_x + (lon - (min_lon - pad_x)) / (lon_range + 2 * pad_x) * effective_w
    # Flip Y: geo north -> image top
    py = offset_y + ((max_lat + pad_y) - lat) / (lat_range + 2 * pad_y) * effective_h

    return px, py


def import_geojson_boundary(layout):
    """Open a file dialog, parse a GeoJSON, and set it as the boundary image.

    This function is designed to be called as a button callback from the
    Boundary tab, matching the same signature pattern as import_image().

    Args:
        layout: The MainWindow instance (self).
    """
    from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    path, _ = QFileDialog.getOpenFileName(
        layout,
        "Import GeoJSON Boundary",
        "",
        "GeoJSON (*.geojson *.json);;All Files (*)"
    )
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        QMessageBox.critical(layout, "Import Error", f"Failed to read GeoJSON:\n{e}")
        return

    # Accept FeatureCollection or single Feature
    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif data.get("type") == "Feature":
        features = [data]
    else:
        QMessageBox.critical(
            layout,
            "Import Error",
            "GeoJSON must be a FeatureCollection or Feature. "
            f"Found type: {data.get('type', 'unknown')}"
        )
        return

    if not features:
        QMessageBox.critical(layout, "Import Error", "GeoJSON contains no features.")
        return

    # Compute geographic bounds
    try:
        bbox = _compute_bounds(features)
    except Exception as e:
        QMessageBox.critical(
            layout, "Import Error", f"Failed to compute bounds:\n{e}"
        )
        return

    min_lon, min_lat, max_lon, max_lat = bbox
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat

    # Suggest output dimensions based on aspect ratio
    if lat_span > 0:
        aspect = lon_span / lat_span
    else:
        aspect = 1.0

    # Target ~2000px on the longer axis, maintain aspect ratio
    if aspect >= 1.0:
        default_w = 2000
        default_h = max(1, int(2000 / aspect))
    else:
        default_h = 2000
        default_w = max(1, int(2000 * aspect))

    # Ask user for output image width
    width_str, ok = QInputDialog.getText(
        layout,
        "Output Image Size",
        "Image width (pixels):",
        text=str(default_w)
    )
    if not ok or not width_str.strip():
        return

    try:
        img_w = int(width_str.strip())
    except ValueError:
        QMessageBox.critical(layout, "Import Error", "Invalid width value.")
        return

    if img_w < 10 or img_w > 50000:
        QMessageBox.critical(
            layout, "Import Error", "Width must be between 10 and 50000."
        )
        return

    # Calculate height to maintain aspect ratio
    img_h = max(1, int(img_w / aspect)) if aspect > 0 else img_w

    # Ask user for line thickness
    thickness_str, ok = QInputDialog.getText(
        layout,
        "Boundary Line Thickness",
        "Line width (pixels, 1-10):",
        text="2"
    )
    if not ok or not thickness_str.strip():
        return

    try:
        line_width = int(thickness_str.strip())
    except ValueError:
        line_width = 2

    line_width = max(1, min(10, line_width))

    # Rasterize: white background, black outlines
    img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    drawn_count = 0
    for feature in features:
        for ring in _parse_feature_geometries(feature):
            if len(ring) < 2:
                continue
            pixels = [
                _lonlat_to_pixel(lon, lat, bbox, img_w, img_h)
                for lon, lat in ring
            ]
            # Draw the outline
            for i in range(len(pixels) - 1):
                draw.line(
                    [pixels[i], pixels[i + 1]],
                    fill=(0, 0, 0, 255),
                    width=line_width
                )
            drawn_count += 1

    if drawn_count == 0:
        QMessageBox.critical(
            layout, "Import Error", "No polygon outlines were drawn."
        )
        return

    # Set the image on the boundary display
    layout.boundary_image_display.set_image(img)

    # Check if territory generation is ready
    layout.check_territory_ready()

    QMessageBox.information(
        layout,
        "Import Successful",
        f"Imported {len(features)} feature(s) with {drawn_count} polygon ring(s).\n"
        f"Bounds: {min_lon:.4f}..{max_lon:.4f} lon, {min_lat:.4f}..{max_lat:.4f} lat\n"
        f"Output size: {img_w}x{img_h} px"
    )
