from datetime import datetime,timedelta,timezone
from app.core.constants import ParkingState
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import VehicleObservation

T=datetime(2026,7,19,tzinfo=timezone.utc)
V=VehicleObservation("1","car",.9,(0,0,10,10))

def engine():
    e=ParkingStateEngine(15,3,1); e.update(None,T); return e

def test_quick_pass_does_not_start_session():
    e=engine(); e.update(V,T+timedelta(seconds=1)); result=e.update(None,T+timedelta(seconds=10))
    assert result.current==ParkingState.EMPTY and result.action=="CANDIDATE_CANCELLED"

def test_stable_vehicle_starts_once():
    e=engine(); e.update(V,T); result=e.update(V,T+timedelta(seconds=15)); assert result.action=="PARK_START"
    assert e.update(V,T+timedelta(seconds=20)).action is None

def test_leave_return_and_leave_timeout():
    e=engine(); e.update(V,T); e.update(V,T+timedelta(seconds=15)); e.update(None,T+timedelta(seconds=16))
    assert e.update(V,T+timedelta(seconds=17)).current==ParkingState.OCCUPIED
    e.update(None,T+timedelta(seconds=18)); assert e.update(None,T+timedelta(seconds=24)).current==ParkingState.LEAVING
    assert e.update(None,T+timedelta(seconds=27)).action=="PARK_END"

def test_offline_keeps_active_session():
    e=engine(); e.update(V,T); e.update(V,T+timedelta(seconds=15)); e.camera_offline()
    assert e.has_active_session and e.state==ParkingState.CAMERA_OFFLINE

def test_restart_recovers_existing_session():
    e=ParkingStateEngine(15,3,1); e.restore_active_session(); result=e.update(V,T)
    assert result.action=="RECOVER_SESSION" and result.current==ParkingState.OCCUPIED
