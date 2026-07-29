"""Resource / ResourceSlot 生命周期与归属。"""

import pytest

from electromind.runtime.resource import (
    ConversationResource,
    Resource,
    ResourceSlot,
)


class FakeAsyncClosable:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


class FakeStoreNoClose:
    """Jsonl 风格：没有 close 方法。"""


class FakeStoreWithClose:
    """SQLite 风格：同步 close。"""

    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def test_async_closable_satisfies_resource_protocol():
    assert isinstance(FakeAsyncClosable(), Resource)


def test_conversation_resource_is_resource():
    res = ConversationResource(FakeStoreNoClose())
    assert isinstance(res, Resource)


@pytest.mark.asyncio
async def test_conversation_resource_close_noop_without_close():
    # 没有 close 的 store 不该报错。
    res = ConversationResource(FakeStoreNoClose())
    await res.close()


@pytest.mark.asyncio
async def test_conversation_resource_close_delegates():
    store = FakeStoreWithClose()
    res = ConversationResource(store)
    await res.close()
    assert store.closed == 1


@pytest.mark.asyncio
async def test_owned_slot_releases_resource():
    resource = FakeAsyncClosable()
    slot = ResourceSlot(resource=resource, owned=True)
    await slot.release()
    assert resource.closed == 1


@pytest.mark.asyncio
async def test_borrowed_slot_does_not_release():
    resource = FakeAsyncClosable()
    slot = ResourceSlot(resource=resource, owned=False)
    await slot.release()
    assert resource.closed == 0
