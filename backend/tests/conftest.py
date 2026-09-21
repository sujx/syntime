"""测试共用 fixture。"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_alice(db):
    """成本管理员 alice：登录流与受保护端点测试共用。"""
    Group.objects.get_or_create(name="成本管理员")
    user = User.objects.create_user("alice", password="pw-12345")
    user.groups.add(Group.objects.get(name="成本管理员"))
    return user


@pytest.fixture
def user_norole(db):
    user = User.objects.create_user("bob", password="pw-12345")
    return user
