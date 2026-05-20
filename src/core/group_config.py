"""Core · group_config

群级别持久化配置。

用法：
    from core.group_config import get_group_config, set_group_config

    value = await get_group_config(group_id, "aoe3_battle.broadcast_mode", default="brief")
    await set_group_config(group_id, "aoe3_battle.broadcast_mode", "detailed")
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, TimestampMixin, get_session, register_model


_BigAutoId = BigInteger().with_variant(Integer(), "sqlite")


class GroupConfigRecord(Base, TimestampMixin):
    __tablename__ = "group_config"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("group_id", "key", name="ux_group_config_group_key"),
    )


register_model(GroupConfigRecord, migration_group="core")


async def get_group_config(group_id: int, key: str, *, default: str = "") -> str:
    """读取群配置。不存在时返回 default。"""
    async with get_session() as sess:
        stmt = select(GroupConfigRecord).where(
            GroupConfigRecord.group_id == group_id,
            GroupConfigRecord.key == key,
        )
        record = (await sess.execute(stmt)).scalar_one_or_none()
        if record is None:
            return default
        return record.value


async def set_group_config(group_id: int, key: str, value: str) -> None:
    """写入群配置（upsert）。"""
    async with get_session() as sess:
        stmt = select(GroupConfigRecord).where(
            GroupConfigRecord.group_id == group_id,
            GroupConfigRecord.key == key,
        )
        record = (await sess.execute(stmt)).scalar_one_or_none()
        if record is None:
            record = GroupConfigRecord(group_id=group_id, key=key, value=value)
            sess.add(record)
        else:
            record.value = value
