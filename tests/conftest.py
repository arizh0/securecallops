import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet


# ── Fernet key fixture ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def fernet_key():
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def set_fernet_env(fernet_key, monkeypatch):
    monkeypatch.setenv("FERNET_KEY", fernet_key)
    import app.common.crypto as m
    m._fernet_instance = None
    yield
    m._fernet_instance = None


# ── Mock DB helpers ───────────────────────────────────────────────────────────

def mock_cursor(fetchone=None, fetchall=None, cols=None):
    """Return a mock psycopg2 cursor."""
    cur = MagicMock()
    cur.__enter__ = lambda self: self
    cur.__exit__ = MagicMock(return_value=False)
    cur.description = [SimpleNamespace(name=c) for c in (cols or [])]
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall or []
    return cur


def mock_conn(*cursors):
    """Return a mock psycopg2 connection that yields cursors in order."""
    conn = MagicMock()
    conn.__enter__ = lambda self: self
    conn.__exit__ = MagicMock(return_value=False)
    if len(cursors) == 1:
        conn.cursor.return_value = cursors[0]
    else:
        conn.cursor.side_effect = list(cursors)
    return conn
