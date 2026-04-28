"""海龟汤游戏专属数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.storage import Base, register_model


# SQLite 需要 INTEGER 才能自增
_BigAutoId = BigInteger().with_variant(Integer(), "sqlite")


class SoupPuzzle(Base):
    __tablename__ = "game_turtle_soup_puzzle"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="日常", nullable=False)
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    truth: Mapped[str] = mapped_column(Text, nullable=False)
    key_clues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(16), default="builtin", nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    play_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    win_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_game_turtle_soup_puzzle_source", "source"),
        Index("ix_game_turtle_soup_puzzle_play_count", "play_count"),
    )


register_model(SoupPuzzle, migration_group="game_turtle_soup")


class SoupSessionRecord(Base):
    __tablename__ = "game_turtle_soup_session"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    puzzle_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


register_model(SoupSessionRecord, migration_group="game_turtle_soup")


class SoupQuestion(Base):
    __tablename__ = "game_turtle_soup_question"

    id: Mapped[int] = mapped_column(_BigAutoId, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    asker_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    asked_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_game_turtle_soup_question_session_asked",
            "session_id",
            "asked_at",
        ),
    )


register_model(SoupQuestion, migration_group="game_turtle_soup")
