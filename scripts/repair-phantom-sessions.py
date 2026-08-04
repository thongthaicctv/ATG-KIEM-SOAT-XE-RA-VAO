"""Preview-only classifier for suspected phantom sessions; no apply mode is provided."""
import argparse,hashlib,importlib.util,json
from pathlib import Path


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--camera",required=True); parser.add_argument("--database",default="data/parking.db"); parser.add_argument("--runtime-count",type=int); parser.add_argument("--preview",action="store_true",default=True); args=parser.parse_args(); before=digest(args.database)
    audit_path=Path(__file__).with_name("audit-parking-sessions.py"); spec=importlib.util.spec_from_file_location("audit_sessions",audit_path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); report=module.audit(args.database,args.camera,args.runtime_count)
    suspects=[]
    for group in report["overlapping_open_session_bboxes"]: suspects.append({"sessions":group["sessions"],"classification":"DUPLICATE_SUSPECTED","evidence":{"bbox_iou":group["bbox_iou"]},"action":"REVIEW_REQUIRED"})
    output={"mode":"PREVIEW","database_changed":before!=digest(args.database),"camera":args.camera,"open_sessions":report["open_sessions"],"potential_phantom_sessions":report["potential_phantom_sessions"],"groups":suspects,"note":"No records were changed; backup/apply is intentionally not implemented in Phase 1.4A hotfix."}; print(json.dumps(output,ensure_ascii=False,indent=2))
