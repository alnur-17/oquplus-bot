from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)

    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_quizzes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Стрик: дата последнего визита и число дней подряд
    last_visit: Mapped[date | None] = mapped_column(Date, nullable=True)
    streak_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Предмет для поиска напарника
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    option_1: Mapped[str] = mapped_column(String(200), nullable=False)
    option_2: Mapped[str] = mapped_column(String(200), nullable=False)
    option_3: Mapped[str] = mapped_column(String(200), nullable=False)
    option_4: Mapped[str] = mapped_column(String(200), nullable=False)
    correct_option: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)


class Duel(Base):
    __tablename__ = "duels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Уникальный 6-символьный код для присоединения
    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False, index=True)
    # Чат, в который отправляются вопросы дуэли
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    challenger_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opponent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # ID квизов через запятую: "3,7,12"
    quiz_ids: Mapped[str] = mapped_column(String(50), nullable=False)
    challenger_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opponent_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Сколько вопросов каждый уже ответил (0-3)
    challenger_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opponent_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # waiting → active → finished
    status: Mapped[str] = mapped_column(String(20), default="waiting", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
