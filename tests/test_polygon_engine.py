import pytest
from app.services.polygon_engine import PolygonEngine,VehicleObservation

def vehicle(track,bbox,confidence=.8): return VehicleObservation(str(track),"car",confidence,bbox)

def test_primary_vehicle_has_highest_overlap():
    engine=PolygonEngine([(0,0),(100,0),(100,100),(0,100)])
    assert engine.primary([vehicle(1,(90,20,130,80)),vehicle(2,(10,10,80,90))]).track_id=="2"

def test_invalid_polygon_rejected():
    with pytest.raises(ValueError): PolygonEngine([(0,0),(10,10),(0,10),(10,0)])

