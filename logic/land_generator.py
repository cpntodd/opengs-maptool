"""Coastline-to-land-image generator.

Uses cartopy's built-in Natural Earth land/sea polygon data to generate
a land/sea raster image suitable for the tool's Land Image tab.
Ocean pixels are RGB (5, 20, 18), lakes are (0, 255, 0), and
everything else is land (white by default).

Polygons are first clipped to the region of interest and simplified to
the target pixel resolution before rasterization, avoiding artifacts
from drawing massive global polygons through PIL's scanline filler.
"""

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import box as _shapely_box
from shapely.ops import unary_union

from logic.geojson_importer import _lonlat_to_pixel


def _simplify_geom(geom, tolerance):
    """Simplify a shapely geometry, preserving type."""
    if geom is None or geom.is_empty:
        return geom
    simplified = geom.simplify(tolerance, preserve_topology=True)
    if simplified.is_empty:
        return geom  # don't lose the geometry entirely
    return simplified


def generate_land_image(bbox, img_w, img_h, pad_pct=0.05):
    """Generate a land/sea raster image from Natural Earth land polygons.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) geographic bounds.
        img_w: Output image width in pixels.
        img_h: Output image height in pixels.
        pad_pct: Padding fraction around the bounding box (default 5%).

    Returns:
        PIL Image in RGBA mode: ocean=(5,20,18,255), land=(255,255,255,255),
        lakes=(0,255,0,255).
    """
    import cartopy.feature as cfeature

    ocean_color = (5, 20, 18, 255)
    land_color = (255, 255, 255, 255)
    lake_color = (0, 255, 0, 255)

    min_lon, min_lat, max_lon, max_lat = bbox
    lon_range = max_lon - min_lon
    lat_range = max_lat - min_lat

    # Tolerance for simplification: ~1 pixel in geographic degrees
    tolerance = max(lon_range / img_w, lat_range / img_h)

    # Clip region (slightly expanded to catch coastlines at the edge)
    pad = 0.1
    clip_box = _shapely_box(
        min_lon - lon_range * pad, min_lat - lat_range * pad,
        max_lon + lon_range * pad, max_lat + lat_range * pad,
    )

    def _project_ring(ring_coords):
        return [
            _lonlat_to_pixel(x, y, bbox, img_w, img_h, pad_pct)
            for x, y in ring_coords
        ]

    # Raster canvas
    img = Image.new("RGBA", (img_w, img_h), ocean_color)
    draw = ImageDraw.Draw(img)

    # --- Land ---
    land_feature = cfeature.LAND.with_scale("10m")
    land_union = unary_union([
        g for g in land_feature.geometries() if g is not None and not g.is_empty
    ])
    land_clipped = land_union.intersection(clip_box)
    if land_clipped.is_empty:
        raise RuntimeError(
            "No land polygons intersect the target region. "
            "The region may be entirely ocean."
        )
    land_simple = _simplify_geom(land_clipped, tolerance)

    for poly in (land_simple.geoms if land_simple.geom_type == "MultiPolygon"
                 else [land_simple]):
        if poly.geom_type != "Polygon" or poly.exterior is None:
            continue
        pixels = _project_ring(poly.exterior.coords)
        if len(pixels) >= 3:
            draw.polygon(pixels, fill=land_color, outline=land_color)

    # --- Lakes ---
    lake_feature = cfeature.LAKES.with_scale("10m")
    lake_union = unary_union([
        g for g in lake_feature.geometries() if g is not None and not g.is_empty
    ])
    lake_clipped = lake_union.intersection(clip_box)
    if not lake_clipped.is_empty:
        lake_simple = _simplify_geom(lake_clipped, tolerance)
        for poly in (lake_simple.geoms if lake_simple.geom_type == "MultiPolygon"
                     else [lake_simple]):
            if poly.geom_type != "Polygon" or poly.exterior is None:
                continue
            pixels = _project_ring(poly.exterior.coords)
            if len(pixels) >= 3:
                draw.polygon(pixels, fill=lake_color, outline=lake_color)

    return img
