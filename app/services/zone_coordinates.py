from __future__ import annotations

import numpy as np


def compute_homography(image_points,zone_points):
    import cv2
    if len(image_points)<4 or len(zone_points)<4 or len(image_points)!=len(zone_points): raise ValueError("CALIBRATION_REQUIRES_FOUR_CORRESPONDING_POINTS")
    matrix,mask=cv2.findHomography(np.asarray(image_points,np.float64),np.asarray(zone_points,np.float64),0)
    if matrix is None: raise ValueError("HOMOGRAPHY_INVALID")
    projected=cv2.perspectiveTransform(np.asarray(image_points,np.float64).reshape(-1,1,2),matrix).reshape(-1,2); error=float(np.sqrt(np.mean(np.sum((projected-np.asarray(zone_points))**2,axis=1))))
    return matrix.tolist(),np.linalg.inv(matrix).tolist(),error


def project_point(point,matrix):
    vector=np.asarray([point[0],point[1],1.0],np.float64); result=np.asarray(matrix,np.float64)@vector
    if abs(result[2])<1e-12: raise ValueError("POINT_AT_INFINITY")
    return float(result[0]/result[2]),float(result[1]/result[2])


def virtual_uv(point,canonical_polygon):
    xs=[float(p[0]) for p in canonical_polygon]; ys=[float(p[1]) for p in canonical_polygon]
    if not xs or max(xs)==min(xs) or max(ys)==min(ys): raise ValueError("CANONICAL_POLYGON_INVALID")
    return (point[0]-min(xs))/(max(xs)-min(xs)),(point[1]-min(ys))/(max(ys)-min(ys))
