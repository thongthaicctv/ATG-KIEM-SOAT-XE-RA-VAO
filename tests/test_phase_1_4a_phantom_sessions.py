from datetime import datetime,timezone
from types import SimpleNamespace

from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import ZoneRuntimeState,deduplicate_candidates

NOW=datetime(2026,8,4,tzinfo=timezone.utc)

def camera(): return SimpleNamespace(id=1,zone_type="CAR_ZONE",capacity=4,parking_confirm_seconds=2,exit_confirm_seconds=1,detection_miss_grace_seconds=2,track_lost_grace_seconds=1)
def vehicle(track,bbox=(0,0,100,100),age=1): return VehicleObservation(str(track),"car",.9,bbox,track_age=age,time_since_update=0)

def test_overlapping_old_and_new_track_make_one_runtime():
    assert len(deduplicate_candidates([vehicle(1),vehicle(2,(2,2,102,102),2)]))==1
    zone=ZoneRuntimeState(camera(),1); zone.process([vehicle(1),vehicle(2,(2,2,102,102),2)],NOW,0); assert len(zone.vehicles)==1

def test_track_id_change_keeps_instance_candidate_timer_and_session():
    zone=ZoneRuntimeState(camera(),1); zone.process([vehicle(1)],NOW,0); runtime=next(iter(zone.vehicles.values())); instance=runtime.vehicle_instance_id
    zone.process([vehicle(2,(3,2,103,102))],NOW,1); starts=zone.process([vehicle(3,(4,2,104,102))],NOW,3)
    assert len(zone.vehicles)==1 and next(iter(zone.vehicles.values())).vehicle_instance_id==instance
    assert len([a for a in starts if a.kind=="PARK_START"])==1

def test_short_detection_gap_does_not_create_replacement_runtime():
    zone=ZoneRuntimeState(camera(),1); zone.process([vehicle(1)],NOW,0); instance=next(iter(zone.vehicles)); zone.process([],NOW,1); zone.process([vehicle(5,(2,1,102,101))],NOW,1.5)
    assert list(zone.vehicles)==[instance]

def test_recovery_window_does_not_create_new_candidate():
    zone=ZoneRuntimeState(camera(),stable_frames_after_reconnect=3); zone.camera_offline(); zone.process([vehicle(10)],NOW,0); zone.process([vehicle(10)],NOW,1)
    assert len(zone.vehicles)==0

def test_four_physical_vehicles_never_create_fifth_runtime():
    zone=ZoneRuntimeState(camera(),1); vehicles=[vehicle(i,(i*150,0,i*150+100,100)) for i in range(4)]
    for tick in range(20): zone.process(vehicles,NOW,float(tick))
    assert len(zone.vehicles)==4
