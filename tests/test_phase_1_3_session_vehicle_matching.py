from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.constants import ParkingState
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import PolygonEngine, VehicleObservation
from app.services.session_vehicle_matcher import is_same_session_vehicle


NOW=datetime(2026,8,4,2,0,tzinfo=timezone.utc)


def _session(vehicle_class="car",bbox=(100,100,300,300),seen=NOW):
    x1,y1,x2,y2=bbox
    return SimpleNamespace(vehicle_class=vehicle_class,confirmed_bbox=list(bbox),confirmed_anchor=[(x1+x2)/2,y2],confirmed_bbox_size=[x2-x1,y2-y1],last_confirmed_seen_at=seen)


def _match(session,candidate,now=NOW,**overrides):
    values=dict(max_anchor_distance=120,min_iou=.10,min_size_ratio=.60,max_size_ratio=1.67,track_lost_grace_seconds=5)
    values.update(overrides)
    return is_same_session_vehicle(session,candidate,now,**values)


def test_car_session_rejects_motorcycle_running_through():
    result=_match(_session("car"),VehicleObservation("2","motorcycle",.9,(105,105,295,295)))
    assert not result.matched and result.reason=="class_mismatch"


def test_car_session_rejects_distant_car():
    result=_match(_session(),VehicleObservation("2","car",.9,(600,100,800,300)))
    assert not result.matched and result.reason in {"anchor_too_far","insufficient_iou"}


def test_near_same_class_new_track_matches():
    result=_match(_session(),VehicleObservation("2","car",.9,(110,105,310,305)))
    assert result.matched and result.bbox_iou>.70


def test_same_class_with_very_different_size_is_rejected():
    result=_match(_session(),VehicleObservation("2","car",.9,(100,100,650,650)))
    assert not result.matched and result.reason=="size_ratio_out_of_range"


def test_unrelated_vehicle_does_not_stop_occupied_to_leaving_and_park_end():
    engine=ParkingStateEngine(parking_confirm_seconds=1,exit_confirm_seconds=2,stable_frames_after_reconnect=1,track_lost_grace_seconds=0,detection_miss_grace_seconds=1)
    engine.restore_active_session(); engine.update(VehicleObservation("1","car",.9,(100,100,300,300)),NOW,monotonic_now=0)
    engine.update(None,NOW+timedelta(seconds=2),monotonic_now=2)
    assert engine.update(None,NOW+timedelta(seconds=4),monotonic_now=4).action=="VEHICLE_LEAVING"
    assert engine.update(None,NOW+timedelta(seconds=6),monotonic_now=6).action=="PARK_END"


def test_unrelated_vehicle_in_leaving_cannot_recover_session():
    engine=ParkingStateEngine(1,2,1,0,1); engine.restore_active_session(); correct=VehicleObservation("1","car",.9,(100,100,300,300))
    engine.update(correct,NOW,monotonic_now=0); engine.update(None,NOW+timedelta(seconds=2),monotonic_now=2)
    assert engine.update(None,NOW+timedelta(seconds=3),monotonic_now=3).action=="VEHICLE_LEAVING"
    # MainWindow passes None when the visible candidate fails session matching.
    transition=engine.update(None,NOW+timedelta(seconds=4),monotonic_now=4)
    assert transition.current==ParkingState.LEAVING and transition.action is None


def test_reconnect_accepts_only_strong_stale_signature():
    session=_session(seen=NOW-timedelta(minutes=1))
    correct=_match(session,VehicleObservation("9","car",.9,(105,105,305,305)),allow_stale_reconnect=True)
    wrong=_match(session,VehicleObservation("10","car",.9,(350,100,550,300)),allow_stale_reconnect=True)
    assert correct.matched and correct.reason=="matched_reconnect_signature"
    assert not wrong.matched


def test_polygon_rejects_bbox_that_only_touches_edge_lightly():
    polygon=[(100,100),(500,100),(500,500),(100,500)]
    edge=VehicleObservation("1","car",.9,(480,50,700,250))
    assert PolygonEngine(polygon,.20).evaluate([edge])==[]
