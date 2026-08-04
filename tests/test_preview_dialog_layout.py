from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy

from app.ui.preview_dialog import PreviewDialog,VideoCanvas


def camera(): return SimpleNamespace(id=1,camera_code="CAM-1",parking_position_code="P1")


def test_video_canvas_expands_and_has_no_fixed_maximum(qtbot):
    canvas=VideoCanvas(); qtbot.addWidget(canvas)
    assert canvas.sizePolicy().horizontalPolicy()==QSizePolicy.Policy.Expanding
    assert canvas.sizePolicy().verticalPolicy()==QSizePolicy.Policy.Expanding
    assert canvas.maximumHeight()>=16777215


def test_resize_rescales_from_original_and_keeps_aspect_ratio(qtbot):
    canvas=VideoCanvas(); qtbot.addWidget(canvas); canvas.resize(800,600); canvas.show(); frame=np.zeros((360,640,3),dtype=np.uint8); canvas.set_frame(frame); qtbot.wait(10)
    first=canvas.pixmap().size(); canvas.resize(1200,700); qtbot.wait(10); second=canvas.pixmap().size()
    assert canvas.latest_image.width()==640 and canvas.latest_image.height()==360
    assert second.width()>first.width() and abs(second.width()/second.height()-16/9)<.02


def test_layout_gives_video_stretch_and_legend_no_stretch(qtbot):
    dialog=PreviewDialog(camera()); qtbot.addWidget(dialog); layout=dialog.layout()
    assert layout.stretch(0)==1 and layout.stretch(1)==0
    assert dialog.info.sizePolicy().verticalPolicy()==QSizePolicy.Policy.Fixed


def test_update_replaces_latest_frame_without_queue(qtbot):
    dialog=PreviewDialog(camera()); qtbot.addWidget(dialog); dialog.update_frame(np.zeros((10,20,3),dtype=np.uint8)); dialog.update_frame(np.zeros((30,40,3),dtype=np.uint8))
    assert dialog.video_canvas.latest_image.size().width()==40
    assert not hasattr(dialog.video_canvas,"queue")


def test_fullscreen_toggle_does_not_change_camera_configuration(qtbot):
    dialog=PreviewDialog(camera()); qtbot.addWidget(dialog); dialog.show(); qtbot.mouseDClick(dialog,Qt.MouseButton.LeftButton); assert dialog.isFullScreen(); qtbot.keyPress(dialog,Qt.Key.Key_Escape); assert not dialog.isFullScreen()
