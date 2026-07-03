from shapely.geometry import Polygon

from app.pipeline.filters import ZoneShape, match_zone


def _rect_zone(zone_id: int, x1: float, y1: float, x2: float, y2: float) -> ZoneShape:
    return ZoneShape(
        zone_id=zone_id,
        name=f"z{zone_id}",
        polygon=Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)]),
    )


def test_bbox_center_inside_zone_matches():
    zones = [_rect_zone(1, 0.4, 0.4, 0.6, 0.6)]
    # bbox center is at (0.5, 0.5), which is inside
    assert match_zone((400, 400, 600, 600), 1000, 1000, zones) == 1


def test_bbox_center_outside_zone_no_match():
    zones = [_rect_zone(1, 0.0, 0.0, 0.2, 0.2)]
    assert match_zone((400, 400, 600, 600), 1000, 1000, zones) is None


def test_first_matching_zone_wins():
    zones = [
        _rect_zone(1, 0.0, 0.0, 0.1, 0.1),
        _rect_zone(2, 0.3, 0.3, 0.7, 0.7),
        _rect_zone(3, 0.4, 0.4, 0.6, 0.6),
    ]
    assert match_zone((450, 450, 550, 550), 1000, 1000, zones) == 2


def test_no_zones_returns_none():
    assert match_zone((0, 0, 10, 10), 100, 100, []) is None
