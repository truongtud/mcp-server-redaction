import time
import uuid


class StateManager:
    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: dict[str, dict] = {}
        self._ttl_seconds = ttl_seconds

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "created_at": time.time(),
            "mappings": {},
        }
        return session_id

    def add_mapping(self, session_id: str, placeholder: str, original: str) -> None:
        self._sessions[session_id]["mappings"][placeholder] = original

    def get_mappings(self, session_id: str) -> dict[str, str] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return dict(session["mappings"])

    def prune_expired(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, data in self._sessions.items()
            if now - data["created_at"] > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
