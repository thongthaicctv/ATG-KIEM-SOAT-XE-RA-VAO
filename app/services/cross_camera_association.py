from __future__ import annotations

import math
from dataclasses import dataclass,field

from app.services.session_vehicle_matcher import vehicle_class_family


@dataclass(slots=True)
class ZoneObservation:
    camera_id:int; tracker_generation:int; track_id:str; zone_x:float; zone_y:float; vehicle_class:str; observed_at:object
    color:str|None=None; appearance_similarity:dict[int,float]=field(default_factory=dict); plate_number:str|None=None; quality:float=1.0
    @property
    def track_key(self): return self.camera_id,self.tracker_generation,str(self.track_id)


@dataclass(slots=True)
class AssociationResult:
    matched:list; new_candidates:list; unmatched_identities:list; uncertain_groups:list; duplicate_observations:list


def identity_score(observation,identity,max_distance=.15):
    if vehicle_class_family(observation.vehicle_class)!=vehicle_class_family(getattr(identity,"stabilized_vehicle_class",None)): return -1e9
    distance=math.dist((observation.zone_x,observation.zone_y),(float(getattr(identity,"latest_zone_x",0)),float(getattr(identity,"latest_zone_y",0))))
    if distance>max_distance: return -1e9
    score=.50*(1-distance/max_distance)+.15*float(observation.quality)
    if observation.plate_number and observation.plate_number==getattr(identity,"plate_number",None): score+=.50
    if observation.color and observation.color==getattr(identity,"stabilized_color",None): score+=.10
    score+=.25*float(observation.appearance_similarity.get(identity.id,0))
    return score


class CrossCameraVehicleAssociationService:
    """Global one-to-one assignment using dynamic programming, not camera-local greedy matching."""
    def associate(self,observations,identities,min_score=.35,max_distance=.15):
        observations=list(observations); identities=list(identities); memo={}
        def solve(index,used):
            key=(index,used)
            if key in memo:return memo[key]
            if index==len(observations): return 0,()
            best_score,best_pairs=solve(index+1,used)
            for j,identity in enumerate(identities):
                if used>>j&1: continue
                score=identity_score(observations[index],identity,max_distance)
                if score<min_score: continue
                tail,pairs=solve(index+1,used|1<<j); candidate=score+tail
                if candidate>best_score: best_score,best_pairs=candidate,((index,j,score),)+pairs
            memo[key]=(best_score,best_pairs); return memo[key]
        _,pairs=solve(0,0); matched=[(observations[i],identities[j],score) for i,j,score in pairs]; matched_obs={id(o) for o,_,_ in matched}; matched_identity={id(i) for _,i,_ in matched}
        # Multiple simultaneous camera observations close to the same matched identity
        # are retained as duplicate sources, not promoted to new physical vehicles.
        duplicates=[]; new=[]; uncertain=[]
        for obs in observations:
            if id(obs) in matched_obs: continue
            candidates=[(identity_score(obs,i,max_distance),i) for _,i,_ in matched]
            candidates=[item for item in candidates if item[0]>=min_score]
            if candidates: duplicates.append((obs,max(candidates,key=lambda x:x[0])[1]))
            elif any(identity_score(obs,i,max_distance)>0 for i in identities): uncertain.append(obs)
            else:
                same=next((candidate for candidate in new if candidate.camera_id!=obs.camera_id and vehicle_class_family(candidate.vehicle_class)==vehicle_class_family(obs.vehicle_class) and math.dist((candidate.zone_x,candidate.zone_y),(obs.zone_x,obs.zone_y))<=max_distance),None)
                if same is None:new.append(obs)
                else:duplicates.append((obs,same))
        return AssociationResult(matched,new,[i for i in identities if id(i) not in matched_identity],uncertain,duplicates)


class IndependentZoneAssociationService:
    def associate(self,*_args,**_kwargs): raise RuntimeError("CROSS_CAMERA_ASSOCIATION_DISABLED_FOR_INDEPENDENT_ZONE")
