"""
类别接口测试（需测试DB）：登录可读、含种子类别、未登录401
"""
from tests.conftest import register_and_login, requires_db


@requires_db
def test_categories_require_auth(client):
    assert client.get("/api/categories").status_code == 401


@requires_db
def test_categories_list_contains_seeds(client):
    """种子数据含差旅费/餐饮费（conftest种子id 1/2）"""
    headers = register_and_login(client, "cat_e1")
    resp = client.get("/api/categories", headers=headers)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "差旅费" in names and "餐饮费" in names
