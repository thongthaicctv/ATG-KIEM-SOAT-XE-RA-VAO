from dataclasses import dataclass

from app.utils.geometry import bbox_anchor, bbox_polygon_overlap, point_in_polygon, polygon_is_valid


@dataclass(slots=True)
class VehicleObservation:
    track_id: str
    vehicle_class: str
    confidence: float
    bbox: tuple[float, float, float, float]
    overlap: float = 0.0
    anchor_inside: bool = False
    track_age: int = 1
    time_since_update: int = 0


class PolygonEngine:
    def __init__(self, polygon: list[tuple[float,float]], overlap_threshold: float=0.30):
        if not polygon_is_valid(polygon): raise ValueError("Polygon không hợp lệ hoặc tự cắt")
        self.polygon=polygon; self.overlap_threshold=overlap_threshold

    def evaluate(self, observations: list[VehicleObservation]) -> list[VehicleObservation]:
        accepted=[]
        for item in observations:
            item.overlap=bbox_polygon_overlap(item.bbox,self.polygon); item.anchor_inside=point_in_polygon(bbox_anchor(item.bbox),self.polygon)
            if item.anchor_inside or item.overlap>=self.overlap_threshold:
                accepted.append(item)
        return sorted(accepted,key=lambda x:(x.anchor_inside,x.overlap,x.confidence),reverse=True)

    def primary(self, observations: list[VehicleObservation]):
        candidates=self.evaluate(observations)
        return candidates[0] if candidates else None
