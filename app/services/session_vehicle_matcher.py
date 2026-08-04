from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import cv2
import numpy as np

from app.services.tracker import bbox_iou
from app.utils.geometry import bbox_anchor
from app.utils.time_utils import ensure_utc


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: bool
    reason: str
    anchor_distance: float
    bbox_iou: float
    size_ratio: float
    class_match: bool
    lost_elapsed_seconds: float
    confidence: float = 0.0
    class_family_match: bool = False
    appearance_similarity: float = 0.0


def vehicle_class_family(value):
    name=str(value or "").strip().lower()
    if name=="motorcycle": return "two_wheel"
    if name in {"car","truck","bus"}: return "four_wheel"
    return name or "unknown"


def _bbox_size(bbox):
    return max(1.0,float(bbox[2])-float(bbox[0])),max(1.0,float(bbox[3])-float(bbox[1]))


def attach_vehicle_signature(vehicle,frame):
    h,w=frame.shape[:2]; x1,y1,x2,y2=[int(v) for v in vehicle.bbox]; x1=max(0,min(w-1,x1)); x2=max(x1+1,min(w,x2)); y1=max(0,min(h-1,y1)); y2=max(y1+1,min(h,y2))
    vehicle.bbox_normalized=(x1/w,y1/h,x2/w,y2/h); anchor=bbox_anchor(vehicle.bbox); vehicle.anchor_normalized=(anchor[0]/w,anchor[1]/h); crop=frame[y1:y2,x1:x2]
    if crop.size:
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV); hist=cv2.calcHist([hsv],[0,1],None,[8,8],[0,180,0,256]); cv2.normalize(hist,hist); vehicle.appearance_histogram=hist.flatten().astype(float).tolist()
        gray=cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(9,8)); bits=(gray[:,1:]>gray[:,:-1]).flatten(); vehicle.perceptual_hash=f"{sum(int(bit)<<index for index,bit in enumerate(bits)):016x}"
    return vehicle


def _appearance_similarity(session,candidate):
    old=getattr(session,"vehicle_histogram",None); new=getattr(candidate,"appearance_histogram",None); score=0.0
    if old and new and len(old)==len(new): score=max(0.0,min(1.0,float(cv2.compareHist(np.asarray(old,np.float32),np.asarray(new,np.float32),cv2.HISTCMP_CORREL))))
    old_hash=getattr(session,"vehicle_perceptual_hash",None); new_hash=getattr(candidate,"perceptual_hash",None)
    if old_hash and new_hash:
        distance=(int(old_hash,16)^int(new_hash,16)).bit_count()/64; score=max(score,1.0-distance)
    return score


def is_same_session_vehicle(active_session,candidate_track,now,max_anchor_distance=120.0,min_iou=.10,min_size_ratio=.60,max_size_ratio=1.67,track_lost_grace_seconds=5.0,allow_stale_reconnect=False):
    previous_bbox=active_session.confirmed_bbox
    previous_anchor=active_session.confirmed_anchor
    previous_size=active_session.confirmed_bbox_size
    class_match=vehicle_class_family(active_session.vehicle_class)==vehicle_class_family(candidate_track.vehicle_class)
    last_seen=active_session.last_confirmed_seen_at
    lost_elapsed=max(0.0,(ensure_utc(now)-ensure_utc(last_seen)).total_seconds()) if last_seen else float("inf")
    if not previous_bbox or not previous_anchor or not previous_size:
        return MatchResult(False,"missing_confirmed_signature",float("inf"),0.0,0.0,class_match,lost_elapsed,0.0,class_match,0.0)
    candidate_anchor=bbox_anchor(candidate_track.bbox); anchor_distance=math.dist(tuple(previous_anchor),candidate_anchor)
    iou=bbox_iou(tuple(previous_bbox),candidate_track.bbox); cw,ch=_bbox_size(candidate_track.bbox); old_area=max(1.0,float(previous_size[0])*float(previous_size[1])); size_ratio=(cw*ch)/old_area
    if not class_match: reason="class_mismatch"
    elif not float(min_size_ratio)<=size_ratio<=float(max_size_ratio): reason="size_ratio_out_of_range"
    elif anchor_distance>float(max_anchor_distance): reason="anchor_too_far"
    elif iou<float(min_iou): reason="insufficient_iou"
    elif lost_elapsed>float(track_lost_grace_seconds) and allow_stale_reconnect and iou>=max(.35,float(min_iou)) and anchor_distance<=float(max_anchor_distance)*.5: reason="matched_reconnect_signature"
    elif lost_elapsed>float(track_lost_grace_seconds): reason="lost_grace_exceeded"
    else: reason="matched"
    appearance=_appearance_similarity(active_session,candidate_track); anchor_score=max(0.0,1.0-anchor_distance/max(1.0,float(max_anchor_distance))); size_score=max(0.0,1.0-abs(1.0-size_ratio)); confidence=(.30*(1.0 if class_match else 0.0)+.25*iou+.20*anchor_score+.15*size_score+.10*appearance)
    return MatchResult(reason in ("matched","matched_reconnect_signature"),reason,anchor_distance,iou,size_ratio,class_match,lost_elapsed,confidence,class_match,appearance)


def match_reconnected_vehicle(open_session,candidate_vehicle,recovery_context=None):
    context=recovery_context or {}
    return is_same_session_vehicle(open_session,candidate_vehicle,context.get("now",datetime.now().astimezone()),max_anchor_distance=context.get("max_anchor_distance",120.0),min_iou=context.get("min_iou",.10),min_size_ratio=context.get("min_size_ratio",.60),max_size_ratio=context.get("max_size_ratio",1.67),track_lost_grace_seconds=context.get("track_lost_grace_seconds",5.0),allow_stale_reconnect=True)
