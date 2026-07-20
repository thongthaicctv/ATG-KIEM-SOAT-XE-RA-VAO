from datetime import datetime,timedelta,timezone
import pytest
from app.database.models import Camera,ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation

T=datetime(2026,7,19,tzinfo=timezone.utc); V=VehicleObservation("10","car",.9,(1,1,5,5))

def setup(db):
    c=Camera(camera_code="CAM01",camera_name="Cổng",parking_position_code="A01",rtsp_url="mock",enabled=True); db.add(c); db.commit(); return c,ParkingSessionService(ParkingRepository(db))

def test_create_link_and_close_session(db):
    c,srv=setup(db); s=srv.start(c,V,T,T+timedelta(seconds=15)); assert s.session_code=="A01-20260719-000001"
    srv.link_track(s,VehicleObservation("11","car",.8,(1,1,5,5)),T+timedelta(seconds=16)); assert len(s.track_links)==2
    srv.end(s,c.id,V,T+timedelta(seconds=30)); assert s.status=="COMPLETED" and s.parking_duration_seconds==15

def test_only_one_active_session_and_unique_codes(db):
    c,srv=setup(db); first=srv.start(c,V,T,T+timedelta(seconds=15)); second=srv.start(c,VehicleObservation("20","car",.8,(1,1,5,5)),T,T+timedelta(seconds=20)); assert second.id==first.id

def test_recovery_reuses_session(db):
    c,srv=setup(db); s=srv.start(c,V,T,T); recovered=srv.recover(s,VehicleObservation("99","car",.8,(1,1,5,5)),T+timedelta(seconds=2)); assert recovered.id==s.id and recovered.status=="RECOVERED"

