from datetime import datetime,timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import Camera,ParkingSession,PhysicalZone,VehicleObservationRecord,ZoneCamera,ZoneGeometryVersion
from app.services.cross_camera_association import CrossCameraVehicleAssociationService,IndependentZoneAssociationService,ZoneObservation
from app.services.plate_observation import PlateObservationService
from app.services.session_creation_gate import SessionCreationGate
from app.services.shared_zone_presence import SharedZonePresenceService
from app.services.zone_coordinates import compute_homography,project_point,virtual_uv
from app.services.zone_geometry_migration import ZoneGeometryMigrationService

NOW=datetime(2026,1,1,tzinfo=timezone.utc)


def observation(camera,track,x,y): return ZoneObservation(camera,0,track,x,y,"car",NOW,color="white")


def test_shared_zone_two_cameras_make_one_new_identity_candidate():
    result=CrossCameraVehicleAssociationService().associate([observation(1,"a",.5,.5),observation(2,"b",.51,.49)],[])
    assert len(result.new_candidates)==1 and len(result.duplicate_observations)==1


def test_global_assignment_is_one_to_one_and_handover_keeps_identity():
    identities=[SimpleNamespace(id=10,stabilized_vehicle_class="car",latest_zone_x=.2,latest_zone_y=.2,stabilized_color="white",plate_number=None),SimpleNamespace(id=20,stabilized_vehicle_class="car",latest_zone_x=.8,latest_zone_y=.8,stabilized_color="white",plate_number=None)]
    result=CrossCameraVehicleAssociationService().associate([observation(2,"new-a",.21,.2),observation(3,"new-b",.79,.8)],identities)
    assert {identity.id for _,identity,_ in result.matched}=={10,20}
    assert len({id(identity) for _,identity,_ in result.matched})==2


def test_independent_zone_forbids_cross_camera_matching():
    with pytest.raises(RuntimeError,match="DISABLED_FOR_INDEPENDENT_ZONE"): IndependentZoneAssociationService().associate([],[])


def test_homography_and_virtual_coordinates():
    matrix,_,error=compute_homography([(0,0),(100,0),(100,100),(0,100)],[(0,0),(1,0),(1,1),(0,1)])
    point=project_point((50,25),matrix); u,v=virtual_uv(point,[(0,0),(1,0),(1,1),(0,1)])
    assert error<1e-9 and u==pytest.approx(.5) and v==pytest.approx(.25)


def database(tmp_path):
    path=tmp_path/"legacy.db"; engine=create_engine(f"sqlite:///{path}"); Base.metadata.create_all(engine); db=sessionmaker(bind=engine,expire_on_commit=False)()
    camera=Camera(camera_code="A",camera_name="A",parking_position_code="A",rtsp_url="rtsp://x",zone_type="CAR_ZONE",capacity=1,polygon_points=[[0,0],[1,0],[1,1],[0,1]])
    db.add(camera); db.flush(); zone=PhysicalZone(zone_code="Z",zone_name="Z",zone_mode="INDEPENDENT_ZONE",zone_type="CAR_ZONE",capacity=1); db.add(zone); db.flush(); geometry=ZoneGeometryVersion(physical_zone_id=zone.id,version_number=1,canonical_polygon_json=[[0,0],[1,0],[1,1],[0,1]],change_type="INITIAL",is_active=True); db.add(geometry); db.flush(); zone.active_geometry_version_id=geometry.id; link=ZoneCamera(physical_zone_id=zone.id,camera_id=camera.id); db.add(link); db.flush()
    session=ParkingSession(session_code="S",camera_id=camera.id,primary_camera_id=camera.id,physical_zone_id=zone.id,parking_position_code="A",vehicle_class="car",entered_at=NOW,parked_at=NOW,status="ACTIVE"); db.add(session); db.flush()
    obs=VehicleObservationRecord(parking_session_id=session.id,physical_zone_id=zone.id,camera_id=camera.id,track_id="1",observed_at=NOW,bbox_image_json=[10,10,30,30],anchor_image_json=[20,30],bbox_normalized_json=[.1,.1,.3,.3],anchor_normalized_json=[.2,.3],zone_x=.2,zone_y=.3,virtual_u=.2,virtual_v=.3,geometry_version_id=geometry.id); db.add(obs); db.commit()
    return db,camera,zone,geometry,session,obs


def calibration(): return {"calibration_type":"LOCAL_NORMALIZED","calibration_status":"VALID","visible_polygon_image_json":[[0,0],[1,0],[1,1],[0,1]],"visible_polygon_zone_json":[[0,0],[2,0],[2,2],[0,2]],"reprojection_error":0}


def test_preview_does_not_write_and_apply_preserves_raw_and_session_times(tmp_path):
    db,camera,zone,old_geometry,session,obs=database(tmp_path); service=ZoneGeometryMigrationService(db); before=(obs.bbox_image_json[:],obs.anchor_image_json[:],session.parked_at,session.left_at)
    preview=service.preview_geometry_change(zone.id,{camera.id:calibration()}); assert preview.remappable_observations==1 and zone.active_geometry_version_id==old_geometry.id
    new,_,backup=service.apply_geometry_change(zone.id,[[0,0],[2,0],[2,2],[0,2]],{camera.id:calibration()},backup_dir=tmp_path/"backup")
    db.refresh(obs); db.refresh(session); assert backup.exists() and obs.bbox_image_json==before[0] and obs.anchor_image_json==before[1]
    assert session.parked_at.replace(tzinfo=timezone.utc)==before[2] and session.left_at==before[3] and session.id>0 and obs.geometry_version_id==new.id


def test_migration_failure_rolls_back_geometry_and_raw_coordinates(tmp_path):
    db,camera,zone,old_geometry,session,obs=database(tmp_path); service=ZoneGeometryMigrationService(db); raw=obs.anchor_image_json[:]
    with pytest.raises(RuntimeError,match="INJECTED"): service.apply_geometry_change(zone.id,[[0,0],[2,0],[2,2],[0,2]],{camera.id:calibration()},backup_dir=tmp_path/"backup",fail_after_remap=True)
    assert db.scalar(select(ZoneGeometryVersion).where(ZoneGeometryVersion.physical_zone_id==zone.id).order_by(ZoneGeometryVersion.version_number.desc())).id==old_geometry.id
    db.refresh(obs); assert obs.anchor_image_json==raw and obs.geometry_version_id==old_geometry.id


def test_missing_raw_coordinate_is_marked_unavailable(tmp_path):
    db,camera,zone,_,_,obs=database(tmp_path); obs.anchor_image_json=None; obs.anchor_normalized_json=None; db.commit(); service=ZoneGeometryMigrationService(db)
    new,preview,_=service.apply_geometry_change(zone.id,[[0,0],[1,0],[1,1],[0,1]],{camera.id:calibration()},backup_dir=tmp_path/"backup")
    db.refresh(obs); assert preview.unavailable_observations==1 and obs.remap_status=="REMAP_UNAVAILABLE" and obs.geometry_version_id!=new.id


def test_plate_interface_does_not_fabricate_ocr():
    result=PlateObservationService().observe(None,None); assert result.plate_number is None and result.status=="NOT_AVAILABLE"


def test_shared_zone_other_camera_prevents_leaving_and_handover_keeps_session():
    service=SharedZonePresenceService(3); service.observe(7,99,1,0); service.observe(7,99,2,0)
    assert service.camera_missing(7,1,1)=="PRESENT_OTHER_CAMERA"
    assert service.items[7].session_id==99


def test_all_cameras_offline_keeps_recovery_pending():
    service=SharedZonePresenceService(3); service.observe(7,99,1,0); service.camera_offline(1)
    assert service.camera_missing(7,1,100)=="RECOVERY_PENDING" and service.items[7].session_id==99


def test_session_gate_blocks_duplicate_and_association_pending():
    gate=SessionCreationGate(); observation=SimpleNamespace(is_ignored=False,association_complete=False)
    assert gate.evaluate(observation,"SHARED_ZONE",duplicate=True,stable=True).reason=="CROSS_CAMERA_DUPLICATE"
    assert gate.evaluate(observation,"SHARED_ZONE",stable=True).state=="IDENTITY_UNCERTAIN"
