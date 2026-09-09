from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timezone

from app.services.session_vehicle_matcher import vehicle_class_family


@dataclass(frozen=True,slots=True)
class ZoneOccupancySnapshot:
    observed_vehicle_count:int; confirmed_occupancy_count:int; candidate_count:int; leaving_session_count:int; recovery_pending_count:int; unmatched_open_session_count:int; open_database_session_count:int; ignored_detection_count:int; capacity:int; zone_state:str; calculated_at:datetime; session_health_state:str="OK"; slot_conflicts:tuple[str,...]=()


def occupancy_state(count,capacity):
    if count==0:return "EMPTY"
    if count<capacity:return "OCCUPIED"
    if count==capacity:return "FULL"
    return "OVER_CAPACITY"


def is_identity_currently_occupying(runtime,now_monotonic,zone_type=None,current_geometry_version_id=None,occupancy_observation_grace_seconds=2.0,frame_health=True):
    if not frame_health or runtime.state!="OCCUPIED" or runtime.session_id is None:return False
    observation=runtime.observation
    if observation is None or getattr(observation,"ignored",False):return False
    if zone_type and vehicle_class_family(getattr(observation,"vehicle_class",None)) != ("two_wheel" if zone_type=="MOTORCYCLE_ZONE" else "four_wheel"):return False
    observation_geometry=getattr(observation,"geometry_version_id",None)
    if current_geometry_version_id is not None and observation_geometry is not None and observation_geometry!=current_geometry_version_id:return False
    anchor=getattr(observation,"anchor_normalized",None) or getattr(observation,"anchor_zone",None)
    if anchor is None and getattr(observation,"bbox",None) is not None:
        bbox=observation.bbox; anchor=((bbox[0]+bbox[2])/2,bbox[3])
    if anchor is None:return False
    if getattr(runtime,"last_seen_tick",None) is None or now_monotonic-runtime.last_seen_tick>float(occupancy_observation_grace_seconds):return False
    return True


def is_leaving_with_active_session(runtime):
    # Phase 4.7D: mot runtime dang o trang thai LEAVING (vua mat 1 lan detect/track sau
    # khi da OCCUPIED) nhung VAN CON so huu mot ParkingSession dang mo (session_id khong
    # None) VAN duoc tinh la "dang chiem cho" ve mat nghiep vu (effective parking
    # occupancy) - CHUA co PARK_END, phien parking VAN ACTIVE trong DB, xe co the VAN
    # dang dau that su, chi la tam thoi khong duoc detector/tracker quan sat lai trong
    # 1-vai khung hinh. CONFIRMED qua kiem tra doi chieu Windows xac dinh (deterministic
    # cross-check, khong dung camera/DB that): 1 lan mat detect duy nhat lam
    # confirmed_occupancy roi tu 1 xuong 0 roi lai len 1 trong khi CUNG mot ParkingSession
    # van con mo suot - day la loi ngu nghia dem (counting semantics), KHONG phai loi
    # vong doi session (session lifecycle da duoc Phase 4.7C/HOTFIX 1 xac nhan dung).
    #
    # QUAN TRONG - dieu kien recovery_session is None: runtime.recovery_session CHI la
    # None sau khi runtime da duoc XAC NHAN song it nhat 1 lan (matches loop trong
    # process() dat "runtime.recovery_session=None" ngay khi mot RECOVERY_PENDING/
    # IDENTITY_UNCERTAIN/LEAVING runtime duoc khop lai voi 1 detection that). Neu
    # KHONG kiem tra dieu kien nay, mot session PHUC HOI (restore_session() luc khoi
    # dong lai/reconnect) ma KHONG BAO GIO duoc xac nhan lai se CUNG chuyen thang tu
    # RECOVERY_PENDING sang LEAVING (xem nhanh unmatched trong process() - ap dung cho
    # MOI runtime con session_id, bat ke tien than la OCCUPIED hay RECOVERY_PENDING) va
    # bi tinh nham la "van dang chiem cho", CHE GIAU mot mismatch that su (session da mo
    # sau restart nhung KHONG co xe nao xac nhan lai) - VI PHAM muc 5 yeu cau ("Do not
    # suppress a real orphan DB/runtime mismatch"), CONFIRMED gay 2 test regression that
    # (test_runtime_mismatch_returns_to_zero_after_recovered_session_times_out va
    # test_session_runtime_mismatch_warning_reappears_on_real_state_change) truoc khi
    # them dieu kien nay. Vi vay: CHI tinh la "chiem cho" khi runtime tung duoc XAC NHAN
    # song truoc do (recovery_session is None) va gio moi tam thoi mat dau ra - KHONG
    # tinh cho runtime moi duoc phuc hoi tu DB nhung chua bao gio duoc quan sat lai.
    #
    # Day la MOT khai niem nghiep vu KHAC voi is_identity_currently_occupying() (duoc
    # giu nguyen ben duoi, dai dien cho "vua duoc quan sat TUOI trong khung hinh nay" -
    # freshly_observed_occupying) - KHONG duoc lam yeu ham do, vi no van con duoc dung
    # dung cho muc dich rieng cua no (phat hien xe dang thuc su duoc nhin thay). Runtime
    # se ngung duoc tinh la chiem cho ngay khi PARK_END xay ra va no bi loai khoi
    # zone.vehicles (xem ZoneRuntimeState.process()) - KHONG can thay doi gi them o day.
    return runtime.state=="LEAVING" and runtime.session_id is not None and runtime.recovery_session is None


def calculate_zone_occupancy(runtimes,now_monotonic,capacity,zone_type=None,current_geometry_version_id=None,occupancy_observation_grace_seconds=2.0,open_database_session_count=0,ignored_detection_count=0,frame_health=True):
    runtimes=list(runtimes); observed={r.runtime_id for r in runtimes if r.observation is not None and not getattr(r.observation,"ignored",False) and r.last_seen_tick is not None and now_monotonic-r.last_seen_tick<=occupancy_observation_grace_seconds}
    freshly_observed_occupying=[r for r in runtimes if is_identity_currently_occupying(r,now_monotonic,zone_type,current_geometry_version_id,occupancy_observation_grace_seconds,frame_health)]
    leaving_with_session=[r for r in runtimes if is_leaving_with_active_session(r)]
    # Phase 4.7D: "chiem cho hieu dung" (effective_parking_occupancy) = da duoc quan sat
    # TUOI (freshly_observed_occupying, OCCUPIED) HOP VOI dang LEAVING nhung van con
    # session dang mo (leaving_with_session) - hai tap nay KHONG BAO GIO giao nhau (mot
    # runtime chi co DUY NHAT mot state tai 1 thoi diem), nen ghep list truc tiep an toan,
    # khong tao trung lap runtime_id.
    effective_parking_occupancy=freshly_observed_occupying+leaving_with_session
    # Phase 4.7D HOTFIX 1A: leaving_session_count la mot chi so TELEMETRY doc lap voi
    # dieu kien recovery_session is None dung cho effective_parking_occupancy o tren -
    # no phai phan anh DUNG so runtime dang o trang thai LEAVING va con session_id, BAT
    # KE runtime do tung duoc xac nhan song hay chua (recovery_session). Dung
    # len(leaving_with_session) o day la SAI vi leaving_with_session da bi loc bo cac
    # runtime LEAVING con recovery_session (chua xac nhan) - CONFIRMED qua kiem tra doi
    # chieu Windows lan 2: mot session phuc hoi CHUA xac nhan chuyen sang LEAVING bi bao
    # cao leaving=0 du runtime that su dang LEAVING (occupancy/unmatched/health van dung,
    # CHI leaving sai). Tinh lai TRUC TIEP tren toan bo runtimes, khong qua leaving_with_session.
    candidates=sum(r.state=="CANDIDATE" for r in runtimes); leaving=sum(r.state=="LEAVING" and r.session_id is not None for r in runtimes); recovery=sum(r.state in ("RECOVERY_PENDING","IDENTITY_UNCERTAIN") and r.session_id is not None for r in runtimes)
    # Phase 4.7D: unmatched_open PHAI dung CUNG tap "chiem cho hieu dung" nay de doi chieu
    # voi open_database_session_count - neu khong, mot session LEAVING hop le (van con
    # ACTIVE, van chua PARK_END) se bi dem la "unmatched" gia (session_health=RUNTIME_MISMATCH
    # gia) chi vi no vua mat 1 lan detect. Mismatch THAT SU (session mo trong DB nhung
    # KHONG co bat ky runtime OCCUPIED/LEAVING nao dai dien - vd RECOVERY_PENDING/IDENTITY_UNCERTAIN
    # keo dai, hoac session mo coi cua) VAN duoc phat hien dung nhu cu, vi cac runtime do
    # KHONG nam trong effective_parking_occupancy.
    unmatched=max(0,int(open_database_session_count)-len({r.session_id for r in effective_parking_occupancy if r.session_id is not None})); health="RUNTIME_MISMATCH" if unmatched else ("RECOVERY_PENDING" if recovery else "OK")
    count=len({r.runtime_id for r in effective_parking_occupancy}); return ZoneOccupancySnapshot(len(observed),count,candidates,leaving,recovery,unmatched,int(open_database_session_count),int(ignored_detection_count),int(capacity),occupancy_state(count,int(capacity)),datetime.now(timezone.utc),health)


def calculate_shared_zone_occupancy(observations,capacity,open_database_session_count=0):
    current=[o for o in observations if not getattr(o,"is_ignored",False) and getattr(o,"vehicle_identity_id",None) is not None]
    by_identity={o.vehicle_identity_id:o for o in current}; slots={}; conflicts=[]
    for identity,observation in by_identity.items():
        slot=getattr(observation,"virtual_slot_id",None)
        if slot and slot in slots and slots[slot]!=identity: conflicts.append(slot)
        elif slot: slots[slot]=identity
    conflicted=set(conflicts); count=sum(1 for identity,o in by_identity.items() if not getattr(o,"virtual_slot_id",None) or o.virtual_slot_id not in conflicted)+len(conflicted)
    unmatched=max(0,int(open_database_session_count)-count); health="DATABASE_CONFLICT" if conflicts else ("RUNTIME_MISMATCH" if unmatched else "OK")
    return ZoneOccupancySnapshot(len(current),count,0,0,0,unmatched,int(open_database_session_count),0,int(capacity),occupancy_state(count,int(capacity)),datetime.now(timezone.utc),health,tuple(sorted(conflicted)))
