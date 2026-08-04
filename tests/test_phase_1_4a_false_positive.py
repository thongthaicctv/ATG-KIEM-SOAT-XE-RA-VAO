from datetime import datetime,timezone
from types import SimpleNamespace

from app.services.polygon_engine import VehicleObservation
from app.services.vehicle_candidate_validator import VehicleCandidateValidator,ignore_zone_match
from app.services.zone_runtime import ZoneRuntimeState

NOW=datetime(2026,8,4,tzinfo=timezone.utc)
IGNORE=[{"enabled":True,"points":[[0,0],[.4,0],[.4,.5],[0,.5]]}]

def camera(ignore=IGNORE): return SimpleNamespace(id=1,zone_type="MOTORCYCLE_ZONE",capacity=2,parking_confirm_seconds=1,exit_confirm_seconds=1,detection_miss_grace_seconds=2,track_lost_grace_seconds=1,ignore_zones=ignore,ignore_zone_overlap_threshold=.30,min_bbox_area_ratio=0,max_bbox_area_ratio=1)
def motorcycle(track,bbox_norm):
    x1,y1,x2,y2=bbox_norm; return VehicleObservation(str(track),"motorcycle",.8,(x1*1000,y1*1000,x2*1000,y2*1000),bbox_normalized=bbox_norm,anchor_normalized=((x1+x2)/2,y2))

def test_motorcycle_inside_ignore_zone_never_creates_candidate_or_session_action():
    fan=motorcycle(1,(.05,.05,.30,.40)); zone=ZoneRuntimeState(camera(),1)
    actions=[]
    for tick in range(20): actions.extend(zone.process([fan],NOW,float(tick)))
    assert ignore_zone_match(fan,IGNORE,.30) and not zone.vehicles and not any(a.kind=="PARK_START" for a in actions)
    assert len(zone.ignored)==1 and zone.parked_count==0

def test_real_motorcycle_outside_ignore_zone_still_creates_session_action():
    bike=motorcycle(2,(.60,.40,.90,.90)); zone=ZoneRuntimeState(camera(),1); actions=[]
    for tick in range(4): actions.extend(zone.process([bike],NOW,float(tick)))
    assert any(a.kind=="PARK_START" for a in actions)

def test_disabled_ignore_zone_does_not_filter_vehicle():
    fan=motorcycle(1,(.05,.05,.30,.40)); assert not ignore_zone_match(fan,[{"enabled":False,"points":IGNORE[0]["points"]}],.30)

def test_candidate_validator_rejects_abnormal_bbox_area():
    bike=motorcycle(2,(.60,.40,.90,.90)); runtime=SimpleNamespace(observation=bike,class_votes={"motorcycle":3},stabilized_class="motorcycle"); configured=camera([]); configured.max_bbox_area_ratio=.05
    result=VehicleCandidateValidator().validate(runtime,configured); assert not result.valid and result.reject_reason=="BBOX_AREA_OUT_OF_RANGE"

def test_real_motorcycle_near_ignore_but_outside_is_not_rejected():
    bike=motorcycle(2,(.41,.10,.60,.45)); assert not ignore_zone_match(bike,IGNORE,.30)
