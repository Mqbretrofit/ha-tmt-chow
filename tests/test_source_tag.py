"""Tests for account-derived TMT command source tags."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.tmt_chow.api import TmtApiError, TmtChowApi, source_tag_from_user_id
from custom_components.tmt_chow.const import USER_PATH


def test_source_tag_from_user_id_matches_uart_v1_format() -> None:
    assert source_tag_from_user_id(1) == "P0000001"
    assert source_tag_from_user_id(0xABCDEF) == "P0ABCDEF"
    assert source_tag_from_user_id("202713") == "P00317D9"


@pytest.mark.parametrize("value", [True, -1, "", "abc", None])
def test_source_tag_rejects_invalid_profile_ids(value: object) -> None:
    with pytest.raises(TmtApiError):
        source_tag_from_user_id(value)


def test_async_get_source_tag_uses_authenticated_user_profile() -> None:
    api = TmtChowApi(None)  # type: ignore[arg-type]

    async def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == USER_PATH
        return {"id": 0xABCDEF}

    api._request = fake_request  # type: ignore[method-assign]

    assert asyncio.run(api.async_get_source_tag()) == "P0ABCDEF"
