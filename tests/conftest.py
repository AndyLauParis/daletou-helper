"""测试全局夹具：每个用例前清空安全层限流与登录失败计数。"""

from __future__ import annotations

import pytest

import security_layer
from helper.api import auth as auth_api


@pytest.fixture(autouse=True)
def _reset_security_state():
    security_layer.reset_security_state()
    auth_api.reset_login_rate_limit()
    yield
    security_layer.reset_security_state()
    auth_api.reset_login_rate_limit()
