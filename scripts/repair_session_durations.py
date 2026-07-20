from app.database.migrations import init_database
from app.database.repair import repair_session_durations
from app.database.session import engine

if __name__ == "__main__":
    init_database()
    print(f"Đã sửa {repair_session_durations(engine)} phiên có duration sai.")
