from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, User
from rest_framework import serializers

from common.permissions import (
    ROLE_COST_ADMIN,
    ROLE_FINANCE,
    ROLE_OPS,
    RoleMaskedSerializerMixin,
    get_role,
)


class DetailSerializer(RoleMaskedSerializerMixin, serializers.Serializer):
    instance_id = serializers.CharField()
    resource_id = serializers.CharField()
    instance_name = serializers.CharField()
    amount = serializers.CharField()


DATA = {
    "instance_id": "i-123",
    "resource_id": "i-123",
    "instance_name": "web-1",
    "amount": "12.34",
}


def _render(user) -> dict:
    serializer = DetailSerializer(DATA, context={"request": SimpleNamespace(user=user)})
    return serializer.data


@pytest.fixture
def _user_in_group(db):
    def make(group_name: str) -> User:
        user = User.objects.create_user(username=group_name, password="x")
        user.groups.add(Group.objects.get_or_create(name=group_name)[0])
        return user

    return make


def test_finance_masked(_user_in_group):
    data = _render(_user_in_group(ROLE_FINANCE))
    assert data["instance_id"] is None
    assert data["resource_id"] is None
    assert data["instance_name"] is None
    assert data["amount"] == "12.34"


def test_cost_admin_not_masked(_user_in_group):
    data = _render(_user_in_group(ROLE_COST_ADMIN))
    assert data["instance_id"] == "i-123"
    assert data["instance_name"] == "web-1"


def test_ops_not_masked(_user_in_group):
    data = _render(_user_in_group(ROLE_OPS))
    assert data["resource_id"] == "i-123"


def test_anonymous_not_masked(db):
    data = _render(SimpleNamespace(is_authenticated=False))
    assert data["instance_id"] == "i-123"


def test_get_role_no_group(db):
    user = User.objects.create_user(username="nobody", password="x")
    assert get_role(user) is None
    assert get_role(None) is None


def test_serializer_without_request_context():
    serializer = DetailSerializer(DATA)
    assert serializer.data["instance_id"] == "i-123"
