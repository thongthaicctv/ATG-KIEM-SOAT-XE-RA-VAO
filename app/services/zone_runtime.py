from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from math import hypot
from uuid import uuid4

from app.services.polygon_engine import VehicleObservation
from app.services.session_vehicle_matcher import is_same_session_vehicle, vehicle_class_family
from app.services.vehicle_candidate_validator import VehicleCandidateValidator,ignore_zone_match
from app.services.zone_occupancy import calculate_zone_occupancy


ZONE_CLASSES = {
    "CAR_ZONE": {"car", "truck", "bus"},
    "MOTORCYCLE_ZONE": {"motorcycle"},
    "LEGACY_UNSET": set(),
}


def accepts_vehicle(zone_type: str, vehicle_class: str) -> bool:
    return str(vehicle_class).lower() in ZONE_CLASSES.get(str(zone_type), set())


@dataclass(slots=True)
class ZoneAction:
    kind: str
    runtime_id: str
    vehicle: VehicleObservation | None = None
    session_id: int | None = None
    occurred_at: datetime | None = None


@dataclass(slots=True)
class VehicleRuntimeState:
    runtime_id: str = field(default_factory=lambda: uuid4().hex)
    state: str = "CANDIDATE"
    session_id: int | None = None
    session_code: str | None = None
    current_track_id: str | None = None
    vehicle_class: str = "unknown"
    first_seen_at: datetime | None = None
    candidate_tick: float | None = None
    parked_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_seen_tick: float | None = None
    missing_tick: float | None = None
    observation: VehicleObservation | None = None
    class_votes: Counter = field(default_factory=Counter)
    recovery_session: object | None = None
    linked_track_ids: set[str] = field(default_factory=set)
    candidate_frames: int = 1

    @property
    def stabilized_class(self) -> str:
        return self.class_votes.most_common(1)[0][0] if self.class_votes else self.vehicle_class

    @property
    def vehicle_instance_id(self): return self.runtime_id


def _bbox_iou(a,b):
    left=max(a[0],b[0]); top=max(a[1],b[1]); right=min(a[2],b[2]); bottom=min(a[3],b[3]); intersection=max(0,right-left)*max(0,bottom-top)
    area_a=max(0,a[2]-a[0])*max(0,a[3]-a[1]); area_b=max(0,b[2]-b[0])*max(0,b[3]-b[1]); union=area_a+area_b-intersection
    return intersection/union if union else 0.0


def deduplicate_candidates(candidates,iou_threshold=.75):
    current=sorted(candidates,key=lambda c:(c.time_since_update==0,c.confidence,c.track_age),reverse=True); kept=[]
    for candidate in current:
        duplicate=any(vehicle_class_family(candidate.vehicle_class)==vehicle_class_family(other.vehicle_class) and _bbox_iou(candidate.bbox,other.bbox)>=iou_threshold for other in kept)
        if not duplicate: kept.append(candidate)
    return kept


class MultiVehicleAssociationService:
    """Global greedy one-to-one matching; a track/runtime can occur in at most one pair."""

    @staticmethod
    def _score(runtime: VehicleRuntimeState, candidate: VehicleObservation) -> float:
        if vehicle_class_family(runtime.vehicle_class) != vehicle_class_family(candidate.vehicle_class):
            return -1.0
        if runtime.recovery_session is not None:
            result=is_same_session_vehicle(runtime.recovery_session,candidate,datetime.now().astimezone(),allow_stale_reconnect=True)
            return result.confidence if result.matched else -1.0
        old=runtime.observation
        if old is None: return .5
        ax=(old.bbox[0]+old.bbox[2])/2; ay=(old.bbox[1]+old.bbox[3])/2
        bx=(candidate.bbox[0]+candidate.bbox[2])/2; by=(candidate.bbox[1]+candidate.bbox[3])/2
        diagonal=max(1.0,hypot(old.bbox[2]-old.bbox[0],old.bbox[3]-old.bbox[1]))
        distance=hypot(ax-bx,ay-by)/diagonal; iou=_bbox_iou(old.bbox,candidate.bbox)
        track_bonus=.75 if str(runtime.current_track_id)==str(candidate.track_id) else 0.0
        return track_bonus + max(iou,max(0.0,1.0-distance))

    def associate(self, runtimes: list[VehicleRuntimeState], candidates: list[VehicleObservation]):
        ranked=[]
        for runtime in runtimes:
            for candidate in candidates:
                score=self._score(runtime,candidate)
                if score>=.15: ranked.append((score,runtime,candidate))
        ranked.sort(key=lambda item:item[0],reverse=True); used_runtime=set(); used_track=set(); matches=[]
        for score,runtime,candidate in ranked:
            if runtime.runtime_id in used_runtime or str(candidate.track_id) in used_track: continue
            used_runtime.add(runtime.runtime_id); used_track.add(str(candidate.track_id)); matches.append((runtime,candidate,score))
        unmatched_runtime=[r for r in runtimes if r.runtime_id not in used_runtime]
        unmatched_candidates=[c for c in candidates if str(c.track_id) not in used_track]
        return matches,unmatched_runtime,unmatched_candidates


class ZoneRuntimeState:
    def __init__(self,camera,stable_frames_after_reconnect=1,minimum_candidate_frames=3):
        self.camera=camera; self.camera_id=camera.id; self.zone_type=camera.zone_type; self.capacity=max(1,int(camera.capacity)); self.parking_confirm_seconds=float(camera.parking_confirm_seconds); self.exit_confirm_seconds=float(camera.exit_confirm_seconds); self.detection_miss_grace_seconds=float(camera.detection_miss_grace_seconds); self.track_lost_grace_seconds=float(camera.track_lost_grace_seconds); self.occupancy_observation_grace_seconds=float(getattr(camera,"occupancy_observation_grace_seconds",2.0)); self.stable_frames_after_reconnect=max(1,int(stable_frames_after_reconnect)); self.minimum_candidate_frames=max(1,int(minimum_candidate_frames)); self.stable_frames=0; self.online=False; self.vehicles={}; self.association=MultiVehicleAssociationService(); self.validator=VehicleCandidateValidator(); self.ignored=[]; self.ignored_track_ids_logged=set(); self.reconnect_generation=0; self.recovery_active=False; self.last_tick=0.0

    def restore_session(self,session):
        runtime=VehicleRuntimeState(runtime_id=session.vehicle_instance_id or uuid4().hex,state="RECOVERY_PENDING",session_id=session.id,session_code=session.session_code,current_track_id=session.current_track_id,vehicle_class=session.stabilized_vehicle_class or session.vehicle_class or "unknown",first_seen_at=session.entered_at,parked_at=session.parked_at,last_seen_at=session.last_seen_at or session.last_confirmed_seen_at,recovery_session=session)
        runtime.class_votes[runtime.vehicle_class]+=1; runtime.linked_track_ids.add(str(session.current_track_id)); self.vehicles[runtime.runtime_id]=runtime; self.recovery_active=True; return runtime

    def camera_offline(self):
        self.online=False; self.stable_frames=0; self.reconnect_generation+=1; self.recovery_active=True
        for runtime in self.vehicles.values():
            if runtime.session_id is not None: runtime.state="RECOVERY_PENDING"; runtime.missing_tick=None

    def process(self,candidates,now,tick):
        self.online=True; self.last_tick=float(tick); self.stable_frames+=1; actions=[]
        eligible=[c for c in candidates if accepts_vehicle(self.zone_type,c.vehicle_class) and c.time_since_update==0]; self.ignored=[]
        for candidate in eligible:
            if ignore_zone_match(candidate,getattr(self.camera,"ignore_zones",None),getattr(self.camera,"ignore_zone_overlap_threshold",.30)): candidate.ignored=True; candidate.ignore_reason="IGNORE_ZONE"; self.ignored.append(candidate)
        filtered=deduplicate_candidates([c for c in eligible if not c.ignored])
        active=list(self.vehicles.values()); matches,unmatched,unclaimed=self.association.associate(active,filtered)
        for runtime,candidate,_score in matches:
            previous=runtime.state; old_track=runtime.current_track_id; runtime.observation=candidate; runtime.current_track_id=str(candidate.track_id); runtime.linked_track_ids.add(str(candidate.track_id)); runtime.last_seen_at=now; runtime.last_seen_tick=tick; runtime.missing_tick=None; runtime.class_votes[candidate.vehicle_class]+=1; runtime.candidate_frames+=1
            if old_track is not None and str(old_track)!=str(candidate.track_id): actions.append(ZoneAction("TRACK_ASSOCIATED",runtime.runtime_id,candidate,runtime.session_id,now))
            if runtime.state in ("RECOVERY_PENDING","IDENTITY_UNCERTAIN","LEAVING"):
                runtime.state="OCCUPIED"; actions.append(ZoneAction("RECOVER_SESSION" if runtime.recovery_session is not None else "TRACK_RECOVERED",runtime.runtime_id,candidate,runtime.session_id,now)); runtime.recovery_session=None
            elif runtime.state=="CANDIDATE" and runtime.candidate_frames>=self.minimum_candidate_frames and tick-(runtime.candidate_tick if runtime.candidate_tick is not None else tick)>=self.parking_confirm_seconds:
                validation=self.validator.validate(runtime,self.camera)
                if validation.valid: runtime.state="OCCUPIED"; runtime.parked_at=now; runtime.vehicle_class=runtime.stabilized_class; actions.append(ZoneAction("PARK_START",runtime.runtime_id,candidate,None,now))
                else: runtime.state="REJECTED"; actions.append(ZoneAction(f"CANDIDATE_REJECTED:{validation.reject_reason}",runtime.runtime_id,candidate,None,now))
            elif runtime.session_id is not None:
                actions.append(ZoneAction("OBSERVED",runtime.runtime_id,candidate,runtime.session_id,now))
            if previous!=runtime.state: actions.append(ZoneAction("STATE_TRANSITION",runtime.runtime_id,candidate,runtime.session_id,now))
        allow_new_candidates=not self.recovery_active or self.stable_frames>=self.stable_frames_after_reconnect
        for candidate in unclaimed:
            if not allow_new_candidates: continue
            runtime=VehicleRuntimeState(current_track_id=str(candidate.track_id),vehicle_class=candidate.vehicle_class,first_seen_at=now,candidate_tick=tick,last_seen_at=now,last_seen_tick=tick,observation=candidate); runtime.linked_track_ids.add(str(candidate.track_id)); runtime.class_votes[candidate.vehicle_class]+=1; self.vehicles[runtime.runtime_id]=runtime; actions.append(ZoneAction("VEHICLE_CANDIDATE",runtime.runtime_id,candidate,None,now))
        for runtime in unmatched:
            if runtime.state=="CANDIDATE":
                if runtime.last_seen_tick is not None and tick-runtime.last_seen_tick>=self.detection_miss_grace_seconds:
                    actions.append(ZoneAction("CANDIDATE_CANCELLED",runtime.runtime_id,runtime.observation,None,now)); self.vehicles.pop(runtime.runtime_id,None)
            elif runtime.session_id is not None:
                if self.stable_frames<self.stable_frames_after_reconnect: continue
                if runtime.missing_tick is None: runtime.missing_tick=tick; runtime.state="LEAVING"; actions.append(ZoneAction("VEHICLE_LEAVING",runtime.runtime_id,runtime.observation,runtime.session_id,now))
                elif tick-runtime.missing_tick>=max(self.track_lost_grace_seconds,self.detection_miss_grace_seconds)+self.exit_confirm_seconds:
                    actions.append(ZoneAction("PARK_END",runtime.runtime_id,runtime.observation,runtime.session_id,now)); self.vehicles.pop(runtime.runtime_id,None)
        if self.recovery_active and self.stable_frames>=self.stable_frames_after_reconnect: self.recovery_active=False
        return actions

    def occupancy_snapshot(self,open_database_session_count=0): return calculate_zone_occupancy(self.vehicles.values(),self.last_tick,self.capacity,self.zone_type,occupancy_observation_grace_seconds=self.occupancy_observation_grace_seconds,open_database_session_count=open_database_session_count,ignored_detection_count=len(self.ignored),frame_health=self.online)
    @property
    def parked_count(self): return self.occupancy_snapshot().confirmed_occupancy_count
    @property
    def candidate_count(self): return sum(v.state=="CANDIDATE" for v in self.vehicles.values())
    @property
    def state(self):
        if not self.online: return "CAMERA_OFFLINE"
        return self.occupancy_snapshot().zone_state
