from datetime import datetime,timedelta,timezone

from app.core.constants import ParkingState
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import VehicleObservation

T=datetime(2026,7,20,tzinfo=timezone.utc)
V2=VehicleObservation("2","motorcycle",.5,(0,0,10,10))
V3=VehicleObservation("3","motorcycle",.5,(0,0,10,10))


def engine(): return ParkingStateEngine(5,2,1,3,5,5,.40)


def update(e,vehicle,seconds): return e.update(vehicle,T+timedelta(seconds=seconds),monotonic_now=100+seconds)


def test_candidate_survives_one_second_miss():
    e=engine(); update(e,V2,0); result=update(e,None,1)
    assert result.current==ParkingState.VEHICLE_CANDIDATE and e.candidate_miss_elapsed==1


def test_candidate_survives_miss_below_five_seconds():
    e=engine(); update(e,V2,0)
    assert update(e,None,4.9).current==ParkingState.VEHICLE_CANDIDATE


def test_detection_return_keeps_original_candidate_start():
    e=engine(); update(e,V2,0); original=e.candidate_tick; update(e,None,2); update(e,V2,3)
    assert e.candidate_tick==original and e.candidate_miss_elapsed==0


def test_candidate_cancels_only_after_continuous_grace():
    e=engine(); update(e,V2,0); assert update(e,None,5).current==ParkingState.VEHICLE_CANDIDATE
    result=update(e,None,5.01); assert result.current==ParkingState.EMPTY and result.action=="CANDIDATE_CANCELLED"
    assert e.cancel_reason=="detection_miss_grace_exceeded"


def test_track_id_change_keeps_candidate():
    e=engine(); update(e,V2,0); update(e,None,1); update(e,V3,2)
    assert e.state==ParkingState.VEHICLE_CANDIDATE and e.candidate_tick==100 and e.primary.track_id=="3"


def test_intermittent_detection_reaches_occupied_by_presence_ratio():
    e=engine(); update(e,V2,0); update(e,None,1); update(e,V3,2); update(e,None,3); update(e,V3,4); result=update(e,V3,5)
    assert result.current==ParkingState.OCCUPIED and result.action=="PARK_START_RECOVERY" and e.presence_ratio>=.40


def test_occupied_survives_several_raw_zero_updates():
    e=engine(); update(e,V2,0); update(e,V2,5)
    for second in (6,7,8,9,10): assert update(e,None,second).current==ParkingState.OCCUPIED

