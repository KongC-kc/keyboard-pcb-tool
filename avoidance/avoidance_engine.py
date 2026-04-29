"""Avoidance engine: compute final avoidance zones per layer using Shapely."""
from __future__ import annotations

from models.avoidance import AvoidancePolygon
from models.layer_config import FoamLayerConfig
from typing import Optional

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union


def compute_avoidance_zone(
    polygons: list[AvoidancePolygon],
    layer_config: FoamLayerConfig,
) -> Optional[Polygon]:
    """Compute the union of all confirmed avoidance polygons for a given layer.

    Each polygon is expanded (buffered) by its layer-specific expansion value,
    falling back to the layer's default expansion if not overridden.
    """
    confirmed = [p for p in polygons if p.confidence == "confirmed"]
    if not confirmed:
        return None

    expanded = []
    for ap in confirmed:
        if len(ap.vertices) < 3:
            continue
        poly = Polygon(ap.vertices)
        if not poly.is_valid:
            poly = poly.buffer(0)

        expansion = ap.layer_expansions.get(
            layer_config.name, layer_config.default_avoidance_expansion
        )
        if expansion > 0:
            poly = poly.buffer(expansion)
        expanded.append(poly)

    if not expanded:
        return None

    result = unary_union(expanded)
    if isinstance(result, MultiPolygon):
        # Return the largest polygon if union produced multiple
        result = max(result.geoms, key=lambda g: g.area)

    return result


def subtract_avoidance(
    cutout: Polygon,
    avoidance: Optional[Polygon],
) -> Polygon:
    """Subtract avoidance zone from a cutout polygon."""
    if avoidance is None:
        return cutout
    result = cutout.difference(avoidance)
    if result.is_empty:
        return cutout
    if isinstance(result, MultiPolygon):
        return max(result.geoms, key=lambda g: g.area)
    return result
