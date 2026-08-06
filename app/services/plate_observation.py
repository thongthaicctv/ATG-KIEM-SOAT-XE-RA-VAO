from dataclasses import dataclass


@dataclass(frozen=True)
class PlateObservation:
    plate_number: str|None=None; confidence: float=0.0; status: str="NOT_AVAILABLE"


class PlateObservationService:
    """Phase 1.4C interface only. No OCR or fabricated plate value."""
    def observe(self,frame,bbox)->PlateObservation: return PlateObservation()
