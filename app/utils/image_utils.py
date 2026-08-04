from urllib.parse import urlsplit, urlunsplit
import cv2
import numpy as np


def mask_rtsp_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if "@" not in parts.netloc:
            return url
        auth, host = parts.netloc.rsplit("@", 1)
        user = auth.split(":", 1)[0]
        return urlunsplit((parts.scheme, f"{user}:***@{host}", parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


def annotate_frame(frame, polygon_points=None, tracks=None, primary=None,debug=None,detections=None,ignore_zones=None):
    """Tạo bản sao frame có polygon, bbox và track ID để hiển thị."""
    output=frame.copy(); h,w=output.shape[:2]
    if polygon_points:
        pts=np.asarray([[(int(x*w),int(y*h)) for x,y in polygon_points]],dtype=np.int32)
        overlay=output.copy(); cv2.fillPoly(overlay,pts,(0,180,0)); cv2.addWeighted(overlay,.12,output,.88,0,output); cv2.polylines(output,pts,True,(0,255,80),max(2,w//900))
    for zone in ignore_zones or []:
        if isinstance(zone,dict) and not zone.get("enabled",True): continue
        points=zone.get("points",[]) if isinstance(zone,dict) else zone
        if len(points)>=3:
            ignored_pts=np.asarray([[(int(x*w),int(y*h)) for x,y in points]],dtype=np.int32); ignored_overlay=output.copy(); cv2.fillPoly(ignored_overlay,ignored_pts,(160,60,160)); cv2.addWeighted(ignored_overlay,.20,output,.80,0,output); cv2.polylines(output,ignored_pts,True,(200,80,200),max(2,w//900))
    primary_id=str(primary.track_id) if primary else None
    tracked_boxes={tuple(round(v) for v in track.bbox) for track in tracks or []}
    for detection in detections or []:
        if tuple(round(v) for v in detection.bbox) in tracked_boxes: continue
        x1,y1,x2,y2=map(int,detection.bbox); cv2.rectangle(output,(x1,y1),(x2,y2),(255,120,0),2); cv2.putText(output,f"DETECTED_NO_TRACK {detection.vehicle_class} {detection.confidence:.2f}",(x1,max(25,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,120,0),2,cv2.LINE_AA)
    for track in tracks or []:
        x1,y1,x2,y2=map(int,track.bbox); is_ignored=getattr(track,"ignored",False); is_primary=str(track.track_id)==primary_id and not is_ignored; color=(160,80,160) if is_ignored else ((0,60,255) if is_primary else (0,220,255))
        anchor=(int((x1+x2)/2),y2); cv2.rectangle(output,(x1,y1),(x2,y2),color,max(2,w//1000)); cv2.circle(output,anchor,6,(255,0,255),-1)
        label=f"{'IGNORED ' if is_ignored else ('PRIMARY ' if is_primary else '')}{track.vehicle_class} #{track.track_id} {track.confidence:.2f}{' reason=IGNORE_ZONE' if is_ignored else ''} age={track.track_age} tsu={track.time_since_update} overlap={track.overlap:.2f} inside={track.anchor_inside}"
        cv2.putText(output,label,(x1,max(25,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,max(.45,w/2800),color,2,cv2.LINE_AA)
    if debug:
        lines=[f"STATE: {debug.get('state','-')}",f"Candidate: {debug.get('candidate_elapsed',0):.1f}s  Miss: {debug.get('candidate_miss_elapsed',0):.1f}s  Presence: {debug.get('presence_ratio',0):.2f}",f"Leaving: {debug.get('leaving_elapsed',0):.1f}s  Cancel: {debug.get('candidate_cancel_reason') or '-'}",f"Raw: {debug.get('raw_detections',0)} Vehicle: {debug.get('vehicle_detections',0)} Polygon: {debug.get('vehicles_in_polygon',0)}",f"Inference: {debug.get('inference_ms',0):.1f} ms Tracker: {debug.get('tracker_status','IDLE')}",f"AI age: {debug.get('ai_frame_age_ms',0):.0f} ms  Display age: {debug.get('preview_frame_age_ms',0):.0f} ms",f"Dropped capture/preview: {debug.get('dropped_capture_frames',0)}/{debug.get('dropped_preview_frames',0)}  Capture queue: {debug.get('queue_size',0)}"]
        for i,line in enumerate(lines): cv2.putText(output,line,(12,30+i*26),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,255),2,cv2.LINE_AA)
    return output


def rotate_frame(frame, degrees: int):
    degrees=int(degrees or 0)%360
    if degrees==90: return cv2.rotate(frame,cv2.ROTATE_90_CLOCKWISE)
    if degrees==180: return cv2.rotate(frame,cv2.ROTATE_180)
    if degrees==270: return cv2.rotate(frame,cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def rotate_normalized_polygon(points, old_degrees: int, new_degrees: int):
    """Chuyển polygon khi đổi hướng ảnh, không làm mất vùng đã vẽ."""
    delta=(int(new_degrees)-int(old_degrees))%360
    result=[]
    for x,y in points or []:
        if delta==90: nx,ny=1-y,x
        elif delta==180: nx,ny=1-x,1-y
        elif delta==270: nx,ny=y,1-x
        else: nx,ny=x,y
        result.append([nx,ny])
    return result


def crop_polygon_roi(frame,normalized_points,padding_ratio=.10):
    """Crop bounding ROI của polygon, mở rộng theo mỗi chiều và giữ offset frame gốc."""
    if frame is None or not normalized_points: return frame,(0,0)
    h,w=frame.shape[:2]; xs=[float(p[0])*w for p in normalized_points]; ys=[float(p[1])*h for p in normalized_points]
    x1,x2=min(xs),max(xs); y1,y2=min(ys),max(ys); pad_x=(x2-x1)*padding_ratio; pad_y=(y2-y1)*padding_ratio
    left=max(0,int(x1-pad_x)); top=max(0,int(y1-pad_y)); right=min(w,int(x2+pad_x)); bottom=min(h,int(y2+pad_y))
    if right<=left or bottom<=top: return frame,(0,0)
    return frame[top:bottom,left:right],(left,top)
