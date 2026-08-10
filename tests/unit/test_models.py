"""
tests/unit/test_models.py

Unit tests for Pydantic request/response models.
Pure validation logic — no network, no I/O.
"""

import pytest
from pydantic import ValidationError

from models import UserRequest


@pytest.mark.unit
def test_user_request_valid_minimal():
    u = UserRequest(name="Alice")
    assert u.name == "Alice"
    assert u.email is None
    assert u.age is None


@pytest.mark.unit
def test_user_request_valid_full():
    u = UserRequest(name="Alice", email="alice@example.com", age=30)
    assert u.email == "alice@example.com"
    assert u.age == 30


@pytest.mark.unit
def test_user_request_invalid_email_raises():
    with pytest.raises(ValidationError, match="email"):
        UserRequest(name="Alice", email="not-an-email")


@pytest.mark.unit
def test_user_request_negative_age_raises():
    with pytest.raises(ValidationError, match="positive"):
        UserRequest(name="Alice", age=-1)


@pytest.mark.unit
def test_user_request_zero_age_raises():
    with pytest.raises(ValidationError, match="positive"):
        UserRequest(name="Alice", age=0)


@pytest.mark.unit
def test_user_request_positive_age_accepted():
    u = UserRequest(name="Alice", age=1)
    assert u.age == 1


@pytest.mark.unit
def test_user_request_missing_name_raises():
    with pytest.raises(ValidationError):
        UserRequest()
