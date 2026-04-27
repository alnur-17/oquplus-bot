import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from sqlalchemy import select

from config import settings
from db_engine import AsyncSessionLocal, init_db, seed_quizzes
from handlers import router
from models import Task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Фоновая задача: уведомления за 24 часа до дедлайна
# ---------------------------------------------------------------------------

async def notify_upcoming_deadlines(bot: Bot) -> None:
    """
    Каждый час проверяет задачи с дедлайном через ~24 часа
    и отправляет уведомление в соответствующий чат.
    """
    while True:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            window_start = now + timedelta(hours=23, minutes=50)
            window_end = now + timedelta(hours=24, minutes=10)

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Task).where(
                        Task.is_done == False,           # noqa: E712
                        Task.notified == False,          # noqa: E712
                        Task.deadline >= window_start,
                        Task.deadline <= window_end,
                    )
                )
                tasks = result.scalars().all()

                for task in tasks:
                    deadline_str = task.deadline.strftime("%d.%m.%Y %H:%M")  # type: ignore[union-attr]
                    assignee_str = task.assignee or "команда"
                    text = (
                        f"⏰ <b>Напоминание!</b>\n\n"
                        f"До дедлайна задачи осталось менее 24 часов:\n\n"
                        f"📝 <b>{task.description}</b>\n"
                        f"👤 {assignee_str}\n"
                        f"🕐 {deadline_str}"
                    )
                    try:
                        await bot.send_message(task.chat_id, text, parse_mode="HTML")
                        task.notified = True
                        logger.info(f"Отправлено уведомление для задачи #{task.id}")
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления для задачи #{task.id}: {e}")

                await session.commit()

        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче уведомлений: {e}")

        # Проверяем каждый час
        await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info("Инициализация базы данных...")
    await init_db()
    await seed_quizzes()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands([
        BotCommand(command="start",      description="Главное меню"),
        BotCommand(command="task",       description="Создать задачу"),
        BotCommand(command="status",     description="Активные задачи"),
        BotCommand(command="profile",    description="Профиль, очки, стрик"),
        BotCommand(command="quiz",       description="Случайный вопрос (+10 + streak)"),
        BotCommand(command="top",        description="Топ-5 участников"),
        BotCommand(command="duel",       description="Создать дуэль"),
        BotCommand(command="join",       description="Принять дуэль /join КОД"),
        BotCommand(command="find_buddy", description="Найти напарника по предмету"),
        BotCommand(command="ask",        description="Спросить ИИ-помощника"),
    ])

    dp = Dispatcher()
    dp.include_router(router)

    # Сохраняем ссылку на задачу, иначе GC может её удалить
    notification_task = asyncio.create_task(notify_upcoming_deadlines(bot))

    logger.info("OQU+ Бот-Командер запущен.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        notification_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notification_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
