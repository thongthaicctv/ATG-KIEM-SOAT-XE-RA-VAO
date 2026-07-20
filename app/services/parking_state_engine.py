from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import deque

from app.core.constants import ParkingState
from .polygon_engine import VehicleObservation


@dataclass(slots=True)
class StateTransition:
    previous: ParkingState
    current: ParkingState
    action: str | None = None
    vehicle: VehicleObservation | None = None


class ParkingStateEngine:
    def __init__(self, parking_confirm_seconds=15.0, exit_confirm_seconds=3.0, stable_frames_after_reconnect=20,track_lost_grace_seconds=0.0,detection_miss_grace_seconds=5.0,presence_window_seconds=5.0,presence_ratio_threshold=.40):
        self.parking_confirm_seconds=parking_confirm_seconds; self.exit_confirm_seconds=exit_confirm_seconds
        self.stable_frames_after_reconnect=stable_frames_after_reconnect; self.track_lost_grace_seconds=track_lost_grace_seconds; self.detection_miss_grace_seconds=detection_miss_grace_seconds; self.presence_window_seconds=presence_window_seconds; self.presence_ratio_threshold=presence_ratio_threshold; self.state=ParkingState.UNKNOWN
        self.candidate_since=None; self.empty_since=None; self.lost_since=None; self.last_vehicle_seen_at=None; self.candidate_tick=None; self.empty_tick=None; self.lost_tick=None; self.last_vehicle_seen_tick=None; self.candidate_miss_elapsed=0.0; self.presence_ratio=0.0; self.cancel_reason=None; self.presence_samples=deque(); self.stable_frames=0; self.primary=None; self.has_active_session=False; self.startup_mode=True

    def _record_presence(self,tick,present):
        self.presence_samples.append((tick,bool(present)))
        while self.presence_samples and tick-self.presence_samples[0][0]>self.presence_window_seconds: self.presence_samples.popleft()
        self.presence_ratio=sum(1 for _,value in self.presence_samples if value)/len(self.presence_samples) if self.presence_samples else 0.0

    def _start_candidate(self,vehicle,now,tick):
        self.state=ParkingState.VEHICLE_CANDIDATE; self.primary=vehicle; self.candidate_since=now; self.candidate_tick=tick; self.last_vehicle_seen_at=now; self.last_vehicle_seen_tick=tick; self.candidate_miss_elapsed=0; self.cancel_reason=None; self.presence_samples.clear(); self._record_presence(tick,True)

    def restore_active_session(self): self.has_active_session=True; self.state=ParkingState.UNKNOWN

    def camera_offline(self):
        previous=self.state; self.state=ParkingState.CAMERA_OFFLINE
        return StateTransition(previous,self.state,"CAMERA_OFFLINE",self.primary)

    def update(self, vehicle: VehicleObservation | None, now: datetime, camera_online=True,monotonic_now=None):
        tick=float(monotonic_now if monotonic_now is not None else now.timestamp())
        previous=self.state
        if not camera_online: return self.camera_offline()
        if self.state==ParkingState.CAMERA_OFFLINE: self.state=ParkingState.UNKNOWN; self.stable_frames=0
        if self.state==ParkingState.UNKNOWN:
            self.stable_frames+=1
            if self.stable_frames<self.stable_frames_after_reconnect: return StateTransition(previous,self.state)
            if self.has_active_session:
                if vehicle: self.primary=vehicle; self.state=ParkingState.OCCUPIED; return StateTransition(previous,self.state,"RECOVER_SESSION",vehicle)
                self.state=ParkingState.LEAVING; self.empty_since=now; self.empty_tick=tick; return StateTransition(previous,self.state,"VEHICLE_LEAVING")
            if vehicle: self._start_candidate(vehicle,now,tick)
            else: self.state=ParkingState.EMPTY; self.primary=None; self.candidate_since=None; self.candidate_tick=None
            if not vehicle: self.startup_mode=False
            return StateTransition(previous,self.state,"VEHICLE_CANDIDATE" if vehicle else None,vehicle)
        if self.state==ParkingState.EMPTY:
            if vehicle:
                self._start_candidate(vehicle,now,tick)
                return StateTransition(previous,self.state,"VEHICLE_CANDIDATE",vehicle)
        elif self.state==ParkingState.VEHICLE_CANDIDATE:
            same_vehicle_type=vehicle is not None and (self.primary is None or vehicle.vehicle_class==self.primary.vehicle_class)
            if same_vehicle_type:
                self.primary=vehicle; self.last_vehicle_seen_at=now; self.last_vehicle_seen_tick=tick; self.candidate_miss_elapsed=0; self._record_presence(tick,True)
            else:
                self._record_presence(tick,False); self.candidate_miss_elapsed=max(0,tick-(self.last_vehicle_seen_tick if self.last_vehicle_seen_tick is not None else tick))
                if self.candidate_miss_elapsed>self.detection_miss_grace_seconds:
                    self.cancel_reason="detection_miss_grace_exceeded"; self.state=ParkingState.EMPTY; self.primary=None; self.candidate_since=None; self.candidate_tick=None; self.last_vehicle_seen_tick=None; self.startup_mode=False
                    return StateTransition(previous,self.state,"CANDIDATE_CANCELLED")
            positive_samples=sum(1 for _,present in self.presence_samples if present)
            if self.candidate_tick is not None and tick-self.candidate_tick>=self.parking_confirm_seconds and self.presence_ratio>=self.presence_ratio_threshold and (vehicle is not None or positive_samples>=2):
                self.state=ParkingState.OCCUPIED; self.has_active_session=True
                action="PARK_START_RECOVERY" if self.startup_mode else "PARK_START"; self.startup_mode=False
                return StateTransition(previous,self.state,action,self.primary)
        elif self.state==ParkingState.OCCUPIED:
            if vehicle:
                if self.primary is None or vehicle.vehicle_class==self.primary.vehicle_class: self.primary=vehicle
                self.last_vehicle_seen_at=now; self.last_vehicle_seen_tick=tick; self.lost_since=None; self.lost_tick=None; self._record_presence(tick,True)
            else:
                self._record_presence(tick,False)
                if self.lost_since is None:
                    self.lost_since=now; self.lost_tick=tick
                    if self.track_lost_grace_seconds>0: return StateTransition(previous,self.state,"TRACK_LOST",self.primary)
                grace=max(self.track_lost_grace_seconds,self.detection_miss_grace_seconds)
                if tick-(self.lost_tick if self.lost_tick is not None else tick)<grace: return StateTransition(previous,self.state,None,self.primary)
                self.state=ParkingState.LEAVING; self.empty_since=now; self.empty_tick=tick
                return StateTransition(previous,self.state,"VEHICLE_LEAVING",self.primary)
        elif self.state==ParkingState.LEAVING:
            if vehicle:
                self.state=ParkingState.OCCUPIED; self.empty_since=None; self.empty_tick=None; self.lost_since=None; self.lost_tick=None; self.primary=vehicle
                return StateTransition(previous,self.state,"TRACK_RECOVERED",vehicle)
            if self.empty_tick is not None and tick-self.empty_tick>=self.exit_confirm_seconds:
                self.state=ParkingState.EMPTY; self.has_active_session=False; self.empty_since=None; self.empty_tick=None
                old=self.primary; self.primary=None
                return StateTransition(previous,self.state,"PARK_END",old)
        return StateTransition(previous,self.state,None,self.primary)
