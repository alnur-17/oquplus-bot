import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from models import Base, Quiz

logger = logging.getLogger(__name__)

_db_url = settings.DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = "postgresql+asyncpg://" + _db_url[len("postgres://"):]
elif _db_url.startswith("postgresql://"):
    _db_url = "postgresql+asyncpg://" + _db_url[len("postgresql://"):]

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Стартовые квизы — добавляются один раз при первом запуске
# ---------------------------------------------------------------------------

_SEED_QUIZZES = [
    # IT
    {
        "question": "Что такое Python?",
        "option_1": "Язык программирования",
        "option_2": "Операционная система",
        "option_3": "База данных",
        "option_4": "Веб-браузер",
        "correct_option": 1,
        "category": "IT",
    },
    {
        "question": "Какой тег создаёт заголовок первого уровня в HTML?",
        "option_1": "<p>",
        "option_2": "<h1>",
        "option_3": "<div>",
        "option_4": "<title>",
        "correct_option": 2,
        "category": "IT",
    },
    {
        "question": "Что означает аббревиатура API?",
        "option_1": "Automated Program Installer",
        "option_2": "Advanced Protocol Integration",
        "option_3": "Application Programming Interface",
        "option_4": "Applied Python Interface",
        "correct_option": 3,
        "category": "IT",
    },
    {
        "question": "Что делает команда git commit?",
        "option_1": "Удаляет файлы из репозитория",
        "option_2": "Сохраняет изменения в историю репозитория",
        "option_3": "Отправляет код на сервер",
        "option_4": "Создаёт новую ветку",
        "correct_option": 2,
        "category": "IT",
    },
    {
        "question": "Какой тип данных в Python хранит пары ключ-значение?",
        "option_1": "list",
        "option_2": "tuple",
        "option_3": "set",
        "option_4": "dict",
        "correct_option": 4,
        "category": "IT",
    },
    # English
    {
        "question": "Что означает слово 'deadline'?",
        "option_1": "Начало проекта",
        "option_2": "Список задач",
        "option_3": "Срок сдачи / крайний срок",
        "option_4": "Перерыв в работе",
        "correct_option": 3,
        "category": "English",
    },
    {
        "question": "Как переводится 'to collaborate'?",
        "option_1": "Соревноваться",
        "option_2": "Игнорировать",
        "option_3": "Отменять",
        "option_4": "Сотрудничать",
        "correct_option": 4,
        "category": "English",
    },
    {
        "question": "Выбери правильный перевод слова 'achievement':",
        "option_1": "Достижение",
        "option_2": "Провал",
        "option_3": "Задание",
        "option_4": "Попытка",
        "correct_option": 1,
        "category": "English",
    },
    {
        "question": "Предложение 'I am studying' в Past Simple:",
        "option_1": "I was study",
        "option_2": "I studied",
        "option_3": "I have studied",
        "option_4": "I am studied",
        "correct_option": 2,
        "category": "English",
    },
    {
        "question": "Что означает 'efficient'?",
        "option_1": "Медленный",
        "option_2": "Устаревший",
        "option_3": "Эффективный",
        "option_4": "Сложный",
        "correct_option": 3,
        "category": "English",
    },
    # Math
    {
        "question": "Чему равно 2¹⁰?",
        "option_1": "512",
        "option_2": "2048",
        "option_3": "1024",
        "option_4": "256",
        "correct_option": 3,
        "category": "Math",
    },
    {
        "question": "Производная функции f(x) = x² равна:",
        "option_1": "x",
        "option_2": "2x",
        "option_3": "2",
        "option_4": "x²/2",
        "correct_option": 2,
        "category": "Math",
    },
    {
        "question": "Сумма углов любого треугольника равна:",
        "option_1": "180°",
        "option_2": "90°",
        "option_3": "360°",
        "option_4": "270°",
        "correct_option": 1,
        "category": "Math",
    },
    {
        "question": "Чему равен log₂(8)?",
        "option_1": "2",
        "option_2": "4",
        "option_3": "8",
        "option_4": "3",
        "correct_option": 4,
        "category": "Math",
    },
    {
        "question": "√144 = ?",
        "option_1": "11",
        "option_2": "12",
        "option_3": "13",
        "option_4": "14",
        "correct_option": 2,
        "category": "Math",
    },
]


async def init_db() -> None:
    """Создаёт таблицы и добавляет новые колонки в существующие таблицы."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ALTER TABLE IF NOT EXISTS безопасно — ничего не сломает если колонка уже есть
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_visit DATE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subject VARCHAR(50)",
        ]
        for sql in migrations:
            await conn.execute(text(sql))


async def seed_quizzes() -> None:
    """Добавляет стартовые квизы, если таблица пуста."""
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Quiz))
        if count == 0:
            session.add_all([Quiz(**q) for q in _SEED_QUIZZES])
            await session.commit()
            logger.info("Добавлено %d квизов в БД.", len(_SEED_QUIZZES))
