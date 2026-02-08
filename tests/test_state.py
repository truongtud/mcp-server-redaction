import time
from mcp_server_redaction.state import StateManager


class TestStateManager:
    def test_create_session_returns_uuid(self):
        sm = StateManager()
        session_id = sm.create_session()
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID4 format

    def test_store_and_retrieve_mapping(self):
        sm = StateManager()
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "john@example.com")
        sm.add_mapping(session_id, "[PERSON_1]", "John Smith")

        mappings = sm.get_mappings(session_id)
        assert mappings == {
            "[EMAIL_1]": "john@example.com",
            "[PERSON_1]": "John Smith",
        }

    def test_get_mappings_unknown_session_returns_none(self):
        sm = StateManager()
        assert sm.get_mappings("nonexistent-id") is None

    def test_expired_sessions_are_pruned(self):
        sm = StateManager(ttl_seconds=0)
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "test@test.com")
        time.sleep(0.01)
        sm.prune_expired()
        assert sm.get_mappings(session_id) is None

    def test_non_expired_sessions_survive_prune(self):
        sm = StateManager(ttl_seconds=3600)
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "test@test.com")
        sm.prune_expired()
        assert sm.get_mappings(session_id) is not None
