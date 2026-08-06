from __future__ import annotations

import shutil
from dataclasses import dataclass,field
from datetime import datetime
from pathlib import Path
from sqlalchemy import func,select

from app.database.models import CameraZoneCalibration,ParkingSession,PhysicalZone,VehicleObservationRecord,ZoneCamera,ZoneGeometryVersion
from app.services.zone_coordinates import project_point,virtual_uv
from app.utils.time_utils import utc_now


@dataclass(slots=True)
class GeometryMigrationPreview:
    affected_cameras:int=0; affected_observations:int=0; remappable_observations:int=0; unavailable_observations:int=0; affected_open_sessions:int=0; affected_completed_sessions:int=0; invalid_calibrations:int=0; max_reprojection_error:float=0; warnings:list[str]=field(default_factory=list); blockers:list[str]=field(default_factory=list)


class ZoneGeometryMigrationService:
    def __init__(self,db): self.db=db
    def preview_geometry_change(self,zone_id,calibrations):
        observations=list(self.db.scalars(select(VehicleObservationRecord).where(VehicleObservationRecord.physical_zone_id==zone_id))); camera_ids=set(self.db.scalars(select(ZoneCamera.camera_id).where(ZoneCamera.physical_zone_id==zone_id,ZoneCamera.enabled.is_(True))))
        remappable=sum(1 for o in observations if o.anchor_image_json or o.anchor_normalized_json); invalid=sum(1 for c in calibrations.values() if c.get("calibration_status")!="VALID")
        open_count=self.db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.physical_zone_id==zone_id,ParkingSession.left_at.is_(None))) or 0; completed=self.db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.physical_zone_id==zone_id,ParkingSession.left_at.is_not(None))) or 0
        errors=[float(c.get("reprojection_error") or 0) for c in calibrations.values()]
        blockers=["INVALID_CALIBRATION"] if invalid else []
        return GeometryMigrationPreview(len(camera_ids),len(observations),remappable,len(observations)-remappable,int(open_count),int(completed),invalid,max(errors,default=0),["REMAP_UNAVAILABLE" ] if len(observations)>remappable else [],blockers)
    def backup_database(self,backup_dir):
        source=Path(str(self.db.get_bind().url.database)); target=Path(backup_dir)/f"{source.stem}_geometry_{datetime.now():%Y%m%d_%H%M%S}{source.suffix}"; target.parent.mkdir(parents=True,exist_ok=True)
        if not source.is_file(): raise RuntimeError("DATABASE_BACKUP_SOURCE_NOT_FOUND")
        shutil.copy2(source,target)
        if not target.is_file() or target.stat().st_size!=source.stat().st_size: raise RuntimeError("DATABASE_BACKUP_FAILED")
        return target
    def apply_geometry_change(self,zone_id,canonical_polygon,calibrations,change_type="POLYGON_REDRAW",reason=None,created_by=None,backup_dir=None,fail_after_remap=False):
        preview=self.preview_geometry_change(zone_id,calibrations)
        if preview.blockers: raise ValueError(f"GEOMETRY_MIGRATION_BLOCKED: {preview.blockers}")
        backup=self.backup_database(backup_dir or Path(self.db.get_bind().url.database).parent/"backups")
        try:
            zone=self.db.get(PhysicalZone,zone_id); previous=zone.active_geometry_version_id; number=(self.db.scalar(select(func.max(ZoneGeometryVersion.version_number)).where(ZoneGeometryVersion.physical_zone_id==zone_id)) or 0)+1
            geometry=ZoneGeometryVersion(physical_zone_id=zone_id,version_number=number,canonical_polygon_json=canonical_polygon,previous_version_id=previous,change_type=change_type,change_reason=reason,created_by=created_by,is_active=False); self.db.add(geometry); self.db.flush()
            zone_cameras={z.camera_id:z for z in self.db.scalars(select(ZoneCamera).where(ZoneCamera.physical_zone_id==zone_id,ZoneCamera.enabled.is_(True)))}
            calibration_rows={}
            for camera_id,values in calibrations.items():
                zc=zone_cameras[int(camera_id)]; row=CameraZoneCalibration(zone_camera_id=zc.id,geometry_version_id=geometry.id,**values); self.db.add(row); calibration_rows[int(camera_id)]=row
            self.db.flush(); self.remap_observations(zone_id,geometry,calibration_rows)
            if fail_after_remap: raise RuntimeError("INJECTED_MIGRATION_FAILURE")
            self.remap_open_sessions(zone_id,geometry.id); self.activate_geometry_version(zone,geometry); self.db.commit(); return geometry,preview,backup
        except Exception:
            self.db.rollback(); raise
    def remap_observations(self,zone_id,geometry,calibrations):
        for observation in self.db.scalars(select(VehicleObservationRecord).where(VehicleObservationRecord.physical_zone_id==zone_id)):
            calibration=calibrations.get(observation.camera_id); anchor=observation.anchor_image_json or observation.anchor_normalized_json
            if not anchor or calibration is None: observation.remap_status="REMAP_UNAVAILABLE"; continue
            if calibration.calibration_type=="HOMOGRAPHY": point=project_point(anchor,calibration.homography_matrix_json)
            else: point=tuple(map(float,observation.anchor_normalized_json or anchor))
            u,v=virtual_uv(point,geometry.canonical_polygon_json); observation.zone_x,observation.zone_y=point; observation.virtual_u,observation.virtual_v=u,v; observation.geometry_version_id=geometry.id; observation.remap_status="REMAPPED"
    def remap_open_sessions(self,zone_id,geometry_id):
        sessions=self.db.scalars(select(ParkingSession).where(ParkingSession.physical_zone_id==zone_id,ParkingSession.left_at.is_(None)))
        for session in sessions:
            latest=self.db.scalar(select(VehicleObservationRecord).where(VehicleObservationRecord.parking_session_id==session.id,VehicleObservationRecord.geometry_version_id==geometry_id).order_by(VehicleObservationRecord.observed_at.desc()).limit(1))
            if latest: session.latest_zone_x=latest.zone_x; session.latest_zone_y=latest.zone_y; session.geometry_version_latest=geometry_id
    def activate_geometry_version(self,zone,geometry):
        self.db.query(ZoneGeometryVersion).filter(ZoneGeometryVersion.physical_zone_id==zone.id).update({ZoneGeometryVersion.is_active:False}); geometry.is_active=True; geometry.activated_at=utc_now(); zone.active_geometry_version_id=geometry.id
