from app.utils.geometry import bbox_anchor,bbox_polygon_overlap,denormalize_points,normalize_points,point_in_polygon,polygon_is_valid,polygon_self_intersects

SQUARE=[(0,0),(10,0),(10,10),(0,10)]

def test_point_inside_and_outside():
    assert point_in_polygon((5,5),SQUARE)
    assert not point_in_polygon((20,5),SQUARE)

def test_polygon_validation():
    assert polygon_is_valid(SQUARE)
    assert not polygon_is_valid([(0,0),(1,1)])
    bow=[(0,0),(10,10),(0,10),(10,0)]
    assert polygon_self_intersects(bow)
    assert not polygon_is_valid(bow)

def test_overlap_and_anchor():
    assert bbox_anchor((0,0,10,10))==(5,10)
    assert bbox_polygon_overlap((5,5,15,15),SQUARE)==0.25

def test_normalized_coordinates_survive_resize():
    normalized=normalize_points([(10,10),(90,10),(90,90)],100,100)
    assert denormalize_points(normalized,200,300)==[(20,30),(180,30),(180,270)]

