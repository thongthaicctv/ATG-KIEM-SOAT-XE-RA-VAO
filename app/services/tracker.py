from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timezone
import math

from app.services.polygon_engine import VehicleObservation


def calculate_track_buffer(processing_fps: float,track_lost_grace_seconds: float,minimum=8,maximum=300) -> int:
    return max(minimum,min(maximum,math.ceil(float(processing_fps)*float(track_lost_grace_seconds))))


@dataclass
class TrackState:
    track_id: str
    bbox: tuple[float,float,float,float]
    vehicle_class: str
    confidence: float
    age: int = 1
    hits: int = 1
    time_since_update: int = 0
    last_seen_at: datetime | None = None


def bbox_iou(a,b):
    ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
    iw=max(0,min(ax2,bx2)-max(ax1,bx1)); ih=max(0,min(ay2,by2)-max(ay1,by1)); inter=iw*ih
    union=max(0,(ax2-ax1)*(ay2-ay1))+max(0,(bx2-bx1)*(by2-by1))-inter
    return inter/union if union>0 else 0.0


class CentroidTracker:
    """Tracker persistent theo camera, ghép bằng IoU và khoảng cách tương đối."""
    def __init__(self,max_distance=100,max_missed=15,min_iou=.05):
        self.next_id=1; self.tracks: dict[str,TrackState]={}; self.max_distance=max_distance; self.max_missed=max_missed; self.min_iou=min_iou; self.update_calls=0

    @staticmethod
    def _center(bbox): return ((bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2)

    def _match_score(self,track: TrackState,detection):
        if track.vehicle_class!=detection.vehicle_class: return None
        iou=bbox_iou(track.bbox,detection.bbox); tc=self._center(track.bbox); dc=self._center(detection.bbox); distance=math.dist(tc,dc)
        diagonal=max(math.hypot(track.bbox[2]-track.bbox[0],track.bbox[3]-track.bbox[1]),1)
        allowed=max(self.max_distance,diagonal*1.5)
        if iou<self.min_iou and distance>allowed: return None
        return iou*2.0 + max(0.0,1.0-distance/allowed) - track.time_since_update*.01

    def update(self,detections,frame_index=None,now=None):
        self.update_calls+=1; now=now or datetime.now(timezone.utc)
        for track in self.tracks.values(): track.age+=1; track.time_since_update+=1
        pairs=[]
        for di,detection in enumerate(detections):
            for tid,track in self.tracks.items():
                score=self._match_score(track,detection)
                if score is not None: pairs.append((score,di,tid))
        assigned_detections=set(); assigned_tracks=set()
        for _,di,tid in sorted(pairs,reverse=True):
            if di in assigned_detections or tid in assigned_tracks: continue
            detection=detections[di]; track=self.tracks[tid]; track.bbox=detection.bbox; track.vehicle_class=detection.vehicle_class; track.confidence=detection.confidence; track.hits+=1; track.time_since_update=0; track.last_seen_at=now
            assigned_detections.add(di); assigned_tracks.add(tid)
        for di,detection in enumerate(detections):
            if di in assigned_detections: continue
            tid=str(self.next_id); self.next_id+=1; self.tracks[tid]=TrackState(tid,detection.bbox,detection.vehicle_class,detection.confidence,last_seen_at=now); assigned_tracks.add(tid)
        for tid in list(self.tracks):
            if self.tracks[tid].time_since_update>self.max_missed: del self.tracks[tid]
        output=[]
        for tid in assigned_tracks:
            track=self.tracks[tid]
            output.append(VehicleObservation(tid,track.vehicle_class,track.confidence,track.bbox,track_age=track.age,time_since_update=track.time_since_update))
        return output
