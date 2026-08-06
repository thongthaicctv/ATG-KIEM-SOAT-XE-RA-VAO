from dataclasses import dataclass


@dataclass(frozen=True)
class SessionGateDecision:
    allow:bool; state:str; reason:str


class SessionCreationGate:
    def evaluate(self,observation,zone_mode,matched_identity=None,matched_open_session=None,duplicate=False,stable=False,idempotency_exists=False):
        if getattr(observation,"is_ignored",False): return SessionGateDecision(False,"REJECTED","IGNORE_ZONE")
        if duplicate:return SessionGateDecision(False,"MATCH_EXISTING","CROSS_CAMERA_DUPLICATE")
        if matched_open_session is not None:return SessionGateDecision(False,"MATCH_EXISTING","OPEN_SESSION_MATCHED")
        if matched_identity is not None:return SessionGateDecision(False,"RECOVERY_PENDING","IDENTITY_MATCHED_WITHOUT_SESSION")
        if idempotency_exists:return SessionGateDecision(False,"MATCH_EXISTING","IDEMPOTENCY_KEY_EXISTS")
        if zone_mode=="SHARED_ZONE" and not getattr(observation,"association_complete",False): return SessionGateDecision(False,"IDENTITY_UNCERTAIN","CROSS_CAMERA_ASSOCIATION_PENDING")
        if not stable:return SessionGateDecision(False,"IDENTITY_UNCERTAIN","VIRTUAL_POSITION_NOT_STABLE")
        return SessionGateDecision(True,"NEW_SESSION","ALL_GATES_PASSED")
