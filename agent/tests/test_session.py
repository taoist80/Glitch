"""Unit tests for unified session management (SessionKey, SessionManager)."""

import pytest
from unittest.mock import MagicMock, patch

from glitch.session import Channel, SessionKey, SessionManager


class TestSessionKey:
    """Tests for SessionKey and Channel."""

    def test_pk_telegram_dm(self):
        key = SessionKey.from_telegram_dm(123456789)
        assert key.channel == Channel.TELEGRAM_DM
        assert key.identity == "123456789"
        assert key.pk == "SESSION#telegram#dm:123456789"

    def test_pk_telegram_group(self):
        key = SessionKey.from_telegram_group(-100123)
        assert key.channel == Channel.TELEGRAM_GROUP
        assert key.identity == "-100123"
        assert key.pk == "SESSION#telegram#group:-100123"

    def test_pk_ui_client(self):
        key = SessionKey.from_ui_client("abc123")
        assert key.channel == Channel.UI
        assert key.identity == "abc123"
        assert key.pk == "SESSION#ui#client:abc123"

    def test_sk(self):
        assert SessionKey.sk() == "session"


class TestSessionManager:
    """Tests for SessionManager with mocked DynamoDB."""

    def test_get_or_create_returns_existing_session_id(self):
        manager = SessionManager(table_name="test-table")
        manager._table = MagicMock()
        manager._table.get_item.return_value = {
            "Item": {"pk": "SESSION#ui#client:abc", "sk": "session", "session_id": "existing-id"}
        }
        key = SessionKey.from_ui_client("abc")
        session_id = manager.get_or_create_session(key)
        assert session_id == "existing-id"
        manager._table.get_item.assert_called_once_with(Key={"pk": key.pk, "sk": "session"})

    def test_get_or_create_creates_new_session_id(self):
        manager = SessionManager(table_name="test-table")
        manager._table = MagicMock()
        manager._table.get_item.return_value = {}
        key = SessionKey.from_ui_client("xyz")
        session_id = manager.get_or_create_session(key)
        assert session_id.startswith("ui#client-xyz-")
        assert len(session_id) > len("ui#client-xyz-")
        manager._table.put_item.assert_called_once()
        call_kw = manager._table.put_item.call_args[1]
        call_args = call_kw["Item"]
        assert call_args["pk"] == key.pk
        assert call_args["sk"] == "session"
        assert call_args["session_id"] == session_id
        assert call_args["channel"] == "ui#client"
        assert call_args["identity"] == "xyz"
