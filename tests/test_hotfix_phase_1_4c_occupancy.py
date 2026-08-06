from types import SimpleNamespace

from app.services.zone_occupancy import calculate_shared_zone_occupancy,calculate_zone_occupancy
from app.services.zone_runtime import VehicleRuntimeState
from app.ui.monitor_widget import CameraCard


def vehicle(identity,state="OCCUPIED",seen=100,session=1,ignored=False,track="1"):
    observation=SimpleNamespace(vehicle_class="car",anchor_normalized=(.5,.8),ignored=ignored,track_id=track)
    return VehicleRuntimeState(runtime_id=identity,state=state,session_id=session,current_track_id=track,vehicle_class="car",last_seen_tick=seen,observation=observation)


def snapshot(runtimes,capacity=3,open_db=0): return calculate_zone_occupancy(runtimes,100,capacity,"CAR_ZONE",occupancy_observation_grace_seconds=2,open_database_session_count=open_db)


def test_one_current_vehicle_capacity_three_is_occupied_one_of_three():
    result=snapshot([vehicle("current")]); assert result.confirmed_occupancy_count==1 and result.zone_state=="OCCUPIED"


def test_full_and_over_capacity_use_only_confirmed_current_identity():
    assert snapshot([vehicle(str(i),session=i) for i in range(3)]).zone_state=="FULL"
    result=snapshot([vehicle(str(i),session=i) for i in range(4)]); assert result.confirmed_occupancy_count==4 and result.zone_state=="OVER_CAPACITY"


def test_five_leaving_sessions_do_not_increase_occupancy():
    runtimes=[vehicle("current")]+[vehicle(f"leaving-{i}","LEAVING",99,i+2) for i in range(5)]
    result=snapshot(runtimes,open_db=6); assert result.confirmed_occupancy_count==1 and result.leaving_session_count==5 and result.zone_state=="OCCUPIED"


def test_open_database_and_candidates_are_health_not_capacity():
    runtimes=[vehicle("current"),vehicle("c1","CANDIDATE",100,None),vehicle("c2","CANDIDATE",100,None)]
    result=snapshot(runtimes,open_db=5); assert result.confirmed_occupancy_count==1 and result.candidate_count==2
    assert result.unmatched_open_session_count==4 and result.session_health_state=="RUNTIME_MISMATCH" and result.zone_state=="OCCUPIED"


def test_stale_or_ignored_observation_is_not_counted():
    stale=vehicle("stale",seen=90); ignored=vehicle("ignored",ignored=True)
    assert snapshot([stale,ignored]).confirmed_occupancy_count==0


def test_track_change_same_runtime_identity_does_not_increase_count():
    runtime=vehicle("identity-1",track="old"); runtime.current_track_id="new"; runtime.linked_track_ids={"old","new"}
    assert snapshot([runtime]).confirmed_occupancy_count==1


def shared(identity,camera,slot=None): return SimpleNamespace(vehicle_identity_id=identity,camera_id=camera,is_ignored=False,virtual_slot_id=slot)


def test_shared_zone_deduplicates_same_identity_across_cameras():
    result=calculate_shared_zone_occupancy([shared(1,10),shared(1,20)],3); assert result.observed_vehicle_count==2 and result.confirmed_occupancy_count==1


def test_shared_zone_counts_two_different_identities():
    assert calculate_shared_zone_occupancy([shared(1,10),shared(2,20)],3).confirmed_occupancy_count==2


def test_slot_conflict_counts_slot_once_and_reports_health_warning():
    result=calculate_shared_zone_occupancy([shared(1,10,"CAR-01"),shared(2,20,"CAR-01")],3)
    assert result.confirmed_occupancy_count==1 and result.slot_conflicts==("CAR-01",) and result.session_health_state=="DATABASE_CONFLICT"


def test_card_uses_clear_occupancy_and_separate_session_health(qtbot):
    camera=SimpleNamespace(id=1,camera_code="A",parking_position_code="P",zone_type="CAR_ZONE",capacity=3,preview_fps=5,enabled=True)
    card=CameraCard(camera); qtbot.addWidget(card); card.update_data("OCCUPIED",vehicle="1/3",candidates=2,leaving=5,recovery_pending=0,open_db=5,observed=1,unmatched_open=4,session_health="RUNTIME_MISMATCH",session_runtime_mismatch=True)
    assert "Xe đang chiếm chỗ: 1/3" in card.details.text(); assert "Đang xác nhận rời: 5" in card.debug.text(); assert "Session chưa đối chiếu: 4" in card.debug.text()
