from typing import Any

import pytest


@pytest.fixture
async def trio(make_user: Any) -> tuple[Any, Any, Any]:
    """(user, admin, second admin). `_admin` picks the upload recipient field (userId/toAdminId)."""
    u = await make_user()
    adm, adm2 = await make_user(role="admin"), await make_user(role="admin")
    adm._admin = adm2._admin = True
    return u, adm, adm2
