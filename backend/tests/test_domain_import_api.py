"""域名导入接口测试（api.md 接口14）：权限限成本管理员、multipart CSV、信封返回。"""

from __future__ import annotations

import io

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile

IMPORT_URL = "/api/assets/domains/import/"

_CSV = (
    "域名,注册商,到期时间,实名状态,DNS 服务器,自动续费,项目标签,备注\n"
    'ok.com,阿里云,2027-01-15,已实名,"dns1,dns2",是,projA,忽略我\n'
    'bad domain,阿里云,2027-01-15,已实名,"dns1,dns2",是,projA,\n'
)


def _upload(name: str = "domains.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _CSV.encode("utf-8"), content_type="text/csv")


def _role_user(username: str, role: str) -> User:
    Group.objects.get_or_create(name=role)
    user = User.objects.create_user(username, password="pw-12345")
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.mark.django_db
def test_cost_admin_import_returns_counts_and_errors(api_client, user_alice):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.post(IMPORT_URL, {"file": _upload()}, format="multipart")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert data["successCount"] == 1  # ok.com 入库，bad domain 失败
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 3  # 表头第1行、ok.com 第2行、bad 第3行
    assert "域名" in data["errors"][0]["reason"]


@pytest.mark.django_db
def test_ops_role_forbidden_40300(api_client):
    api_client.force_authenticate(user=_role_user("ops1", "云运维"))
    resp = api_client.post(IMPORT_URL, {"file": _upload()}, format="multipart")
    assert resp.json()["code"] == 40300


@pytest.mark.django_db
def test_finance_role_forbidden_40300(api_client):
    api_client.force_authenticate(user=_role_user("fin1", "财务人员"))
    resp = api_client.post(IMPORT_URL, {"file": _upload()}, format="multipart")
    assert resp.json()["code"] == 40300


@pytest.mark.django_db
def test_unauthenticated_40100(api_client):
    resp = api_client.post(IMPORT_URL, {"file": _upload()}, format="multipart")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


@pytest.mark.django_db
def test_missing_file_is_param_invalid_40001(api_client, user_alice):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.post(IMPORT_URL, {}, format="multipart")
    assert resp.json()["code"] == 40001


@pytest.mark.django_db
def test_utf8_bom_csv_is_accepted(api_client, user_alice):
    """带 BOM 的 CSV（Excel 常见导出）表头仍能识别首列「域名」。"""
    api_client.force_authenticate(user=user_alice)
    bom = io.BytesIO(b"\xef\xbb\xbf" + _CSV.encode("utf-8"))
    upload = SimpleUploadedFile("bom.csv", bom.read(), content_type="text/csv")
    resp = api_client.post(IMPORT_URL, {"file": upload}, format="multipart")
    assert resp.json()["data"]["successCount"] == 1
