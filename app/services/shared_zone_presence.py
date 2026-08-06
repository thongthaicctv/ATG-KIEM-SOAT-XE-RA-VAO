from __future__ import annotations

from dataclasses import dataclass,field


@dataclass
class SharedIdentityPresence:
    vehicle_identity_id:int; session_id:int; observing_cameras:set[int]=field(default_factory=set); missing_since:float|None=None


class SharedZonePresenceService:
    """Session absence is zone-wide: losing one camera never means vehicle departure."""
    def __init__(self,exit_confirm_seconds=3): self.exit_confirm_seconds=float(exit_confirm_seconds); self.items={}; self.offline_cameras=set()
    def restore(self,identity_id,session_id): self.items[identity_id]=SharedIdentityPresence(identity_id,session_id); return self.items[identity_id]
    def observe(self,identity_id,session_id,camera_id,now):
        item=self.items.setdefault(identity_id,SharedIdentityPresence(identity_id,session_id)); item.observing_cameras.add(camera_id); item.missing_since=None; return "PRESENT"
    def camera_missing(self,identity_id,camera_id,now):
        item=self.items[identity_id]; item.observing_cameras.discard(camera_id)
        if item.observing_cameras:return "PRESENT_OTHER_CAMERA"
        if self.offline_cameras:return "RECOVERY_PENDING"
        item.missing_since=now if item.missing_since is None else item.missing_since
        return "LEAVING" if now-item.missing_since<self.exit_confirm_seconds else "PARK_END"
    def camera_offline(self,camera_id): self.offline_cameras.add(camera_id); return "CAMERA_OFFLINE_ONLY"
    def camera_online(self,camera_id): self.offline_cameras.discard(camera_id); return "ZONE_RECOVERY"
