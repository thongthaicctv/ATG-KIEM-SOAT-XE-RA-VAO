from datetime import datetime,timezone
from types import SimpleNamespace

from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import MultiVehicleAssociationService,VehicleRuntimeState,ZoneRuntimeState,accepts_vehicle

NOW=datetime(2026,8,4,tzinfo=timezone.utc)

def camera(zone_type="CAR_ZONE",capacity=2):
    return SimpleNamespace(id=1,zone_type=zone_type,capacity=capacity,parking_confirm_seconds=1,exit_confirm_seconds=1,detection_miss_grace_seconds=1,track_lost_grace_seconds=0)

def car(track,x=0): return VehicleObservation(str(track),"car",.9,(x,0,x+10,10))

def confirm(zone,vehicles):
    zone.process(vehicles,NOW,0); zone.process(vehicles,NOW,1); return zone.process(vehicles,NOW,2)

def test_zone_class_family_filter():
    assert accepts_vehicle("CAR_ZONE","car") and accepts_vehicle("CAR_ZONE","truck")
    assert not accepts_vehicle("CAR_ZONE","motorcycle")
    assert accepts_vehicle("MOTORCYCLE_ZONE","motorcycle") and not accepts_vehicle("MOTORCYCLE_ZONE","car")
    assert not accepts_vehicle("LEGACY_UNSET","car")

def test_two_vehicles_create_independent_candidates_and_full_state():
    zone=ZoneRuntimeState(camera(),1); actions=confirm(zone,[car(1,0),car(2,100)])
    starts=[a for a in actions if a.kind=="PARK_START"]; assert len(starts)==2
    for action in starts: zone.vehicles[action.runtime_id].session_id=int(action.vehicle.track_id)
    assert zone.parked_count==2 and zone.state=="FULL"

def test_one_to_one_association_never_reuses_track():
    runtimes=[VehicleRuntimeState(current_track_id="1",vehicle_class="car",observation=car(1,0)),VehicleRuntimeState(current_track_id="2",vehicle_class="car",observation=car(2,100))]
    matches,_,_=MultiVehicleAssociationService().associate(runtimes,[car(9,2)])
    assert len(matches)==1 and len({m[0].runtime_id for m in matches})==1

def test_one_vehicle_leaves_without_closing_other():
    zone=ZoneRuntimeState(camera(),1); starts=confirm(zone,[car(1,0),car(2,100)])
    for action in starts:
        if action.kind=="PARK_START": zone.vehicles[action.runtime_id].session_id=int(action.vehicle.track_id)
    zone.process([car(2,100)],NOW,4); actions=zone.process([car(2,100)],NOW,7)
    assert [a.session_id for a in actions if a.kind=="PARK_END"]==[1]
    assert zone.parked_count==1

def test_over_capacity_is_aggregate_not_session_rule():
    zone=ZoneRuntimeState(camera(capacity=1),1); starts=confirm(zone,[car(1),car(2,100)])
    for action in starts:
        if action.kind=="PARK_START": zone.vehicles[action.runtime_id].session_id=1
    assert zone.state=="OVER_CAPACITY"
