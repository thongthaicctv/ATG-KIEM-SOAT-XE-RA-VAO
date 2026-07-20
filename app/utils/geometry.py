from __future__ import annotations

from typing import Iterable
import cv2
import numpy as np

Point = tuple[float, float]
BBox = tuple[float, float, float, float]


def normalize_points(points: Iterable[Point], width: int, height: int) -> list[Point]:
    if width <= 0 or height <= 0:
        raise ValueError("Kích thước frame phải lớn hơn 0")
    return [(min(1.0, max(0.0, x / width)), min(1.0, max(0.0, y / height))) for x, y in points]


def denormalize_points(points: Iterable[Point], width: int, height: int) -> list[Point]:
    return [(x * width, y * height) for x, y in points]


def polygon_is_valid(points: list[Point]) -> bool:
    if len(points) < 3 or len(set(points)) < 3:
        return False
    contour = np.asarray(points, dtype=np.float32)
    return abs(cv2.contourArea(contour)) > 1e-8 and not polygon_self_intersects(points)


def _orientation(a: Point, b: Point, c: Point) -> int:
    v = (b[1]-a[1])*(c[0]-b[0]) - (b[0]-a[0])*(c[1]-b[1])
    return 0 if abs(v) < 1e-10 else (1 if v > 0 else 2)


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    return _orientation(a,b,c) != _orientation(a,b,d) and _orientation(c,d,a) != _orientation(c,d,b)


def polygon_self_intersects(points: list[Point]) -> bool:
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i+1) % n]
        for j in range(i+1, n):
            if j in (i, (i+1) % n) or (j+1) % n in (i, (i+1) % n):
                continue
            if _segments_intersect(a, b, points[j], points[(j+1) % n]):
                return True
    return False


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    return cv2.pointPolygonTest(np.asarray(polygon, dtype=np.float32), point, False) >= 0


def bbox_anchor(bbox: BBox) -> Point:
    x1, _, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def bbox_polygon_overlap(bbox: BBox, polygon: list[Point]) -> float:
    x1, y1, x2, y2 = bbox
    area = max(0.0, x2-x1) * max(0.0, y2-y1)
    if area <= 0 or not polygon_is_valid(polygon):
        return 0.0
    rect = np.asarray([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], dtype=np.float32)
    poly = np.asarray(polygon, dtype=np.float32)
    intersection, _ = cv2.intersectConvexConvex(rect, poly)
    if intersection > 0:
        return float(intersection / area)
    # General fallback for concave polygons: rasterize a tight local mask.
    min_x, min_y = int(np.floor(min(x1, min(p[0] for p in polygon)))), int(np.floor(min(y1, min(p[1] for p in polygon))))
    max_x, max_y = int(np.ceil(max(x2, max(p[0] for p in polygon)))), int(np.ceil(max(y2, max(p[1] for p in polygon))))
    scale = max(max_x-min_x, max_y-min_y, 1)
    factor = min(1000/scale, 1.0)
    def pts(v): return np.asarray([[(int((x-min_x)*factor), int((y-min_y)*factor)) for x,y in v]], np.int32)
    shape=(max(1,int((max_y-min_y)*factor)+2), max(1,int((max_x-min_x)*factor)+2))
    m1=np.zeros(shape,np.uint8); m2=np.zeros(shape,np.uint8)
    cv2.fillPoly(m1, pts(polygon), 1); cv2.fillPoly(m2, pts([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]), 1)
    return float(np.logical_and(m1,m2).sum() / max(1,m2.sum()))

