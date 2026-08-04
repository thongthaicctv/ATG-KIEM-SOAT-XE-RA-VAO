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
    occupancy_inside: bool = False
    track_age: int = 1
    time_since_update: int = 0
    bbox_normalized: tuple[float,float,float,float] | None = None
    anchor_normalized: tuple[float,float] | None = None
    appearance_histogram: list[float] | None = None
    perceptual_hash: str | None = None
    ignored: bool = False
    ignore_reason: str | None = None


class PolygonEngine:
    def __init__(self, polygon: list[tuple[float,float]], overlap_threshold: float=0.30):
        if not polygon_is_valid(polygon): raise ValueError("Polygon không hợp lệ hoặc tự cắt")
        self.polygon=polygon; self.overlap_threshold=overlap_threshold

    def evaluate(self, observations: list[VehicleObservation]) -> list[VehicleObservation]:
        accepted=[]
        cx=sum(x for x,_ in self.polygon)/len(self.polygon); cy=sum(y for _,y in self.polygon)/len(self.polygon)
        inner=[(cx+(x-cx)*.90,cy+(y-cy)*.90) for x,y in self.polygon]
        for item in observations:
            anchor=bbox_anchor(item.bbox); item.overlap=bbox_polygon_overlap(item.bbox,self.polygon); item.anchor_inside=point_in_polygon(anchor,self.polygon); item.occupancy_inside=point_in_polygon(anchor,inner)
            if item.occupancy_inside or (item.anchor_inside and item.overlap>=self.overlap_threshold) or item.overlap>=max(.50,self.overlap_threshold):
                accepted.append(item)
        return sorted(accepted,key=lambda x:(x.occupancy_inside,x.anchor_inside,x.overlap,x.confidence),reverse=True)

    def primary(self, observations: list[VehicleObservation]):
        candidates=self.evaluate(observations)
        return candidates[0] if candidates else None
