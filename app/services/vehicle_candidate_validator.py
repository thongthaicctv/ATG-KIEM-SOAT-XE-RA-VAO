from dataclasses import dataclass

from app.utils.geometry import bbox_polygon_overlap,point_in_polygon


@dataclass(slots=True)
class CandidateValidationResult:
    valid: bool
    confidence_mean: float
    class_consistency: float
    ignore_zone_match: bool=False
    background_similarity: float=0.0
    false_positive_similarity: float=0.0
    reject_reason: str | None=None


def ignore_zone_match(vehicle,ignore_zones,overlap_threshold=.30):
    bbox=vehicle.bbox_normalized
    anchor=vehicle.anchor_normalized
    if bbox is None or anchor is None: return False
    for zone in ignore_zones or []:
        if isinstance(zone,dict):
            if not zone.get("enabled",True): continue
            points=[tuple(p) for p in zone.get("points",[])]
        else: points=[tuple(p) for p in zone]
        if len(points)>=3:
            scaled_bbox=tuple(value*1000 for value in bbox); scaled_points=[(x*1000,y*1000) for x,y in points]
            if point_in_polygon(tuple(anchor),points) or bbox_polygon_overlap(scaled_bbox,scaled_points)>=float(overlap_threshold): return True
    return False


class VehicleCandidateValidator:
    """Rule-based validation interface; registry/background validators can be plugged in later."""
    def validate(self,runtime,camera):
        observations=max(1,sum(runtime.class_votes.values())); consistency=runtime.class_votes.get(runtime.stabilized_class,0)/observations; confidence=float(getattr(runtime.observation,"confidence",0)); bbox=runtime.observation.bbox_normalized if runtime.observation else None; area=(bbox[2]-bbox[0])*(bbox[3]-bbox[1]) if bbox else 0
        ignored=bool(runtime.observation and ignore_zone_match(runtime.observation,getattr(camera,"ignore_zones",None),getattr(camera,"ignore_zone_overlap_threshold",.30)))
        reason="IGNORE_ZONE" if ignored else ("BBOX_AREA_OUT_OF_RANGE" if not float(getattr(camera,"min_bbox_area_ratio",0))<=area<=float(getattr(camera,"max_bbox_area_ratio",1)) else ("CLASS_INCONSISTENT" if consistency<.60 else None))
        return CandidateValidationResult(not reason,confidence,consistency,ignore_zone_match=ignored,reject_reason=reason)
