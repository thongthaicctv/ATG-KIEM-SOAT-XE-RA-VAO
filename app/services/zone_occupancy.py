from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timezone

from app.services.session_vehicle_matcher import vehicle_class_family


@dataclass(frozen=True,slots=True)
class ZoneOccupancySnapshot:
    observed_vehicle_count:int; confirmed_occupancy_count:int; candidate_count:int; leaving_session_count:int; recovery_pending_count:int; unmatched_open_session_count:int; open_database_session_count:int; ignored_detection_count:int; capacity:int; zone_state:str; calculated_at:datetime; session_health_state:str="OK"; slot_conflicts:tuple[str,...]=()


def occupancy_state(count,capacity):
    if count==0:return "EMPTY"
    if count<capacity:return "OCCUPIED"
    if count==capacity:return "FULL"
    return "OVER_CAPACITY"


def is_identity_currently_occupying(runtime,now_monotonic,zone_type=None,current_geometry_version_id=None,occupancy_observation_grace_seconds=2.0,frame_health=True):
    if not frame_health or runtime.state!="OCCUPIED" or runtime.session_id is None:return False
    observation=runtime.observation
    if observation is None or getattr(observation,"ignored",False):return False
    if zone_type and vehicle_class_family(getattr(observation,"vehicle_class",None)) != ("two_wheel" if zone_type=="MOTORCYCLE_ZONE" else "four_wheel"):return False
    observation_geometry=getattr(observation,"geometry_version_id",None)
    if current_geometry_version_id is not None and observation_geometry is not None and observation_geometry!=current_geometry_version_id:return False
    anchor=getattr(observation,"anchor_normalized",None) or getattr(observation,"anchor_zone",None)
    if anchor is None and getattr(observation,"bbox",None) is not None:
        bbox=observation.bbox; anchor=((bbox[0]+bbox[2])/2,bbox[3])
    if anchor is None:return False
    if getattr(runtime,"last_seen_tick",None) is None or now_monotonic-runtime.last_seen_tick>float(occupancy_observation_grace_seconds):return False
    return True


def calculate_zone_occupancy(runtimes,now_monotonic,capacity,zone_type=None,current_geometry_version_id=None,occupancy_observation_grace_seconds=2.0,open_database_session_count=0,ignored_detection_count=0,frame_health=True):
    runtimes=list(runtimes); observed={r.runtime_id for r in runtimes if r.observation is not None and not getattr(r.observation,"ignored",False) and r.last_seen_tick is not None and now_monotonic-r.last_seen_tick<=occupancy_observation_grace_seconds}
    occupying=[r for r in runtimes if is_identity_currently_occupying(r,now_monotonic,zone_type,current_geometry_version_id,occupancy_observation_grace_seconds,frame_health)]
    candidates=sum(r.state=="CANDIDATE" for r in runtimes); leaving=sum(r.state=="LEAVING" and r.session_id is not None for r in runtimes); recovery=sum(r.state in ("RECOVERY_PENDING","IDENTITY_UNCERTAIN") and r.session_id is not None for r in runtimes)
    unmatched=max(0,int(open_database_session_count)-len({r.session_id for r in occupying if r.session_id is not None})); health="RUNTIME_MISMATCH" if unmatched else ("RECOVERY_PENDING" if recovery else "OK")
    count=len({r.runtime_id for r in occupying}); return ZoneOccupancySnapshot(len(observed),count,candidates,leaving,recovery,unmatched,int(open_database_session_count),int(ignored_detection_count),int(capacity),occupancy_state(count,int(capacity)),datetime.now(timezone.utc),health)


def calculate_shared_zone_occupancy(observations,capacity,open_database_session_count=0):
    current=[o for o in observations if not getattr(o,"is_ignored",False) and getattr(o,"vehicle_identity_id",None) is not None]
    by_identity={o.vehicle_identity_id:o for o in current}; slots={}; conflicts=[]
    for identity,observation in by_identity.items():
        slot=getattr(observation,"virtual_slot_id",None)
        if slot and slot in slots and slots[slot]!=identity: conflicts.append(slot)
        elif slot: slots[slot]=identity
    conflicted=set(conflicts); count=sum(1 for identity,o in by_identity.items() if not getattr(o,"virtual_slot_id",None) or o.virtual_slot_id not in conflicted)+len(conflicted)
    unmatched=max(0,int(open_database_session_count)-count); health="DATABASE_CONFLICT" if conflicts else ("RUNTIME_MISMATCH" if unmatched else "OK")
    return ZoneOccupancySnapshot(len(current),count,0,0,0,unmatched,int(open_database_session_count),0,int(capacity),occupancy_state(count,int(capacity)),datetime.now(timezone.utc),health,tuple(sorted(conflicted)))
