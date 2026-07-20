import numpy as np
from app.utils.image_utils import mask_rtsp_url,rotate_frame,rotate_normalized_polygon

def test_rtsp_password_is_masked():
    masked=mask_rtsp_url("rtsp://admin:secret@10.0.0.1/live")
    assert "secret" not in masked and "admin:***@" in masked


def test_rotate_frame_and_polygon_counterclockwise():
    frame=np.zeros((2,3,3),dtype=np.uint8)
    assert rotate_frame(frame,270).shape==(3,2,3)
    assert rotate_normalized_polygon([[.2,.3]],0,270)==[[.3,.8]]
