import random
import re
import string
from datetime import date as date_type
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.enums import ChatAction
from aiogram.types import User as TgUser
from sqlalchemy import func, select

from ai_client import ask_tutor, explain_wrong_answer
from db_engine import AsyncSessionLocal
from models import Duel, Quiz, Task, User

router = Router()

# ─── Ранги ────────────────────────────────────────────────────────────────────

_RANK_TABLE = [
    (0,   50,   "Новичок 🌱"),
    (51,  200,  "Студент 📚"),
    (201, 500,  "Мастер ⭐"),
    (501, None, "Эксперт 🏆"),
]


def _rank_info(score: int) -> tuple[str, int | None]:
    """Возвращает (название ранга, очков до следующего или None)."""
    for _, max_s, name in _RANK_TABLE:
        if max_s is None or score <= max_s:
            return name, (max_s - score) if max_s else None
    return "Эксперт 🏆", None


# ─── Стрик ────────────────────────────────────────────────────────────────────

def _update_streak(user: User) -> None:
    """Обновляет last_visit и streak_count пользователя."""
    today = date_type.today()
    if user.last_visit is None:
        user.last_visit = today
        user.streak_count = 1
        return
    delta = (today - user.last_visit).days
    if delta == 0:
        return  # уже заходил сегодня
    elif delta == 1:
        user.streak_count += 1  # стрик продолжается
    else:
        user.streak_count = 1  # пропустил — сброс
    user.last_visit = today


# ─── Пользователь ─────────────────────────────────────────────────────────────

async def _get_or_create_user(session, tg_user: TgUser) -> User:
    """Возвращает пользователя из БД, создавая запись если её нет."""
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "Пользователь",
            last_visit=date_type.today(),
            streak_count=1,
        )
        session.add(user)
        await session.flush()
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name or user.first_name
        _update_streak(user)
    return user


# ─── Задачи — helpers ─────────────────────────────────────────────────────────

def _parse_task_args(raw: str) -> tuple[str, str | None, datetime | None]:
    text = re.sub(r"^/task(?:@\w+)?\s*", "", raw, flags=re.IGNORECASE).strip()

    assignee: str | None = None
    m = re.search(r"@\w+", text)
    if m:
        assignee = m.group(0)
        text = text.replace(assignee, "").strip()

    deadline: datetime | None = None
    dm = re.search(r"\b(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?\b", text)
    if dm:
        try:
            time_str = dm.group(2) or "00:00"
            deadline = datetime.strptime(f"{dm.group(1)} {time_str}", "%d.%m.%Y %H:%M")
        except ValueError:
            pass
        text = text.replace(dm.group(0), "").strip()

    return text.strip(), assignee, deadline


def _format_task(task: Task, index: int) -> str:
    deadline_str = task.deadline.strftime("%d.%m.%Y %H:%M") if task.deadline else "не указан"
    return (
        f"<b>{index}. #{task.id}</b> {task.description}\n"
        f"   👤 {task.assignee or 'не назначен'}  |  ⏰ {deadline_str}"
    )


def _done_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{task_id}")
        ]]
    )


# ─── Дуэль — helpers ──────────────────────────────────────────────────────────

def _generate_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _duel_keyboard(duel_id: int, q_idx: int, options: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{i + 1}. {opt}",
                callback_data=f"dq:{duel_id}:{q_idx}:{i + 1}"
            )]
            for i, opt in enumerate(options)
        ]
    )


async def _send_duel_question(bot: Bot, duel: Duel, q_idx: int, session) -> None:
    quiz_ids = [int(x) for x in duel.quiz_ids.split(",")]
    quiz = await session.get(Quiz, quiz_ids[q_idx])
    if quiz is None:
        return
    options = [quiz.option_1, quiz.option_2, quiz.option_3, quiz.option_4]
    await bot.send_message(
        duel.chat_id,
        f"⚔️ <b>Дуэль — Вопрос {q_idx + 1}/3</b>\n\n{quiz.question}",
        parse_mode="HTML",
        reply_markup=_duel_keyboard(duel.id, q_idx, options),
    )


async def _announce_duel_result(bot: Bot, duel: Duel, session) -> None:
    challenger = await session.get(User, duel.challenger_id)
    opponent = await session.get(User, duel.opponent_id)

    def _name(u: User | None, uid: int) -> str:
        if u and u.username:
            return f"@{u.username}"
        return u.first_name if u else f"#{uid}"

    ch_name = _name(challenger, duel.challenger_id)
    op_name = _name(opponent, duel.opponent_id or 0)

    if duel.challenger_score > duel.opponent_score:
        winner = ch_name
        if challenger:
            challenger.score += 20
    elif duel.opponent_score > duel.challenger_score:
        winner = op_name
        if opponent:
            opponent.score += 20
    else:
        winner = None

    lines = [
        "⚔️ <b>Дуэль завершена!</b>\n",
        f"{ch_name}: <b>{duel.challenger_score}/3</b> правильных",
        f"{op_name}: <b>{duel.opponent_score}/3</b> правильных\n",
        f"🏆 Победитель: <b>{winner}</b> (+20 очков)" if winner else "🤝 <b>Ничья!</b>",
    ]
    await bot.send_message(duel.chat_id, "\n".join(lines), parse_mode="HTML")


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.from_user:
        async with AsyncSessionLocal() as session:
            await _get_or_create_user(session, message.from_user)
            await session.commit()

    await message.answer(
        "👋 <b>OQU+ Бот-Командер</b>\n\n"
        "📋 <b>Задачи:</b>\n"
        "  /task — создать задачу\n"
        "  /status — активные задачи\n\n"
        "🧠 <b>Квизы и рейтинг:</b>\n"
        "  /quiz — вопрос (+10 очков + streak бонус)\n"
        "  /profile — профиль и статистика\n"
        "  /top — топ-5 участников\n\n"
        "⚔️ <b>Дуэли:</b>\n"
        "  /duel — создать дуэль\n"
        "  /join КОД — принять дуэль\n\n"
        "🤝 <b>Напарники:</b>\n"
        "  /find_buddy — найти напарника по предмету\n\n"
        "<b>Формат /task:</b>\n"
        "  <code>/task Описание @исполнитель ДД.ММ.ГГГГ</code>",
        parse_mode="HTML",
    )


# ─── /ask ─────────────────────────────────────────────────────────────────────

@router.message(Command("ask"))
async def cmd_ask(message: Message, bot: Bot) -> None:
    if not message.text:
        return

    question = re.sub(r"^/ask(?:@\w+)?\s*", "", message.text, flags=re.IGNORECASE).strip()

    if not question:
        await message.reply(
            "❓ Задай вопрос:\n"
            "<code>/ask Как работает цикл for в Python?</code>\n"
            "<code>/ask Объясни закон Ома</code>",
            parse_mode="HTML",
        )
        return

    # Показываем индикатор печати пока ждём ответ от Groq
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    answer = await ask_tutor(question)

    await message.reply(
        f"🤖 <b>ИИ-Помощник</b>\n\n{answer}",
        parse_mode="HTML",
    )


# ─── /task ────────────────────────────────────────────────────────────────────

@router.message(Command("task"))
async def cmd_task(message: Message) -> None:
    if not message.text:
        return

    description, assignee, deadline = _parse_task_args(message.text)

    if not description:
        await message.reply(
            "❌ Укажи описание задачи.\n"
            "Пример: <code>/task Сделать презентацию @aibek 28.04.2025</code>",
            parse_mode="HTML",
        )
        return

    async with AsyncSessionLocal() as session:
        if message.from_user:
            await _get_or_create_user(session, message.from_user)
        task = Task(
            chat_id=message.chat.id,
            description=description,
            assignee=assignee,
            deadline=deadline,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

    deadline_str = deadline.strftime("%d.%m.%Y %H:%M") if deadline else "не указан"
    await message.reply(
        f"✅ <b>Задача #{task.id} создана!</b>\n\n"
        f"📝 {description}\n"
        f"👤 {assignee or 'не назначен'}\n"
        f"⏰ {deadline_str}",
        parse_mode="HTML",
        reply_markup=_done_keyboard(task.id),
    )


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .where(Task.chat_id == message.chat.id, Task.is_done == False)  # noqa: E712
            .order_by(Task.deadline.asc().nulls_last(), Task.created_at.asc())
        )
        tasks = result.scalars().all()

    if not tasks:
        await message.answer("🎉 Нет активных задач! Всё выполнено.")
        return

    lines = ["📋 <b>Активные задачи:</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []

    for i, task in enumerate(tasks, start=1):
        lines.append(_format_task(task, i))
        buttons.append([
            InlineKeyboardButton(text=f"✅ #{task.id}", callback_data=f"done:{task.id}")
        ])

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# ─── /profile ─────────────────────────────────────────────────────────────────

@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    if not message.from_user:
        return

    async with AsyncSessionLocal() as session:
        user = await _get_or_create_user(session, message.from_user)
        await session.commit()

    rank_name, pts_to_next = _rank_info(user.score)
    display_name = f"@{user.username}" if user.username else user.first_name
    next_rank_line = (
        f"📈 До следующего ранга: <b>{pts_to_next} очков</b>"
        if pts_to_next is not None else "🎖 Максимальный ранг достигнут!"
    )
    streak_emoji = "🔥" if user.streak_count > 1 else "💤"

    await message.answer(
        "╔══════════════════════════╗\n"
        "║   👤  ПРОФИЛЬ СТУДЕНТА   ║\n"
        "╚══════════════════════════╝\n\n"
        f"🎓 {display_name}\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
        f"{streak_emoji} Стрик: <b>{user.streak_count} дн.</b>  "
        f"<i>(+{user.streak_count * 5} бонус к квизу)</i>\n\n"
        "📊 <b>СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Очки:              <b>{user.score}</b>\n"
        f"✅ Задач выполнено:   <b>{user.completed_tasks}</b>\n"
        f"🧠 Квизов пройдено:   <b>{user.completed_quizzes}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{next_rank_line}",
        parse_mode="HTML",
    )


# ─── /quiz ────────────────────────────────────────────────────────────────────

@router.message(Command("quiz"))
async def cmd_quiz(message: Message) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Quiz).order_by(func.random()).limit(1))
        quiz = result.scalar_one_or_none()

    if quiz is None:
        await message.answer("❌ Квизы не найдены в базе данных.")
        return

    options = [quiz.option_1, quiz.option_2, quiz.option_3, quiz.option_4]
    cat_emoji = {"IT": "💻", "English": "🇬🇧", "Math": "📐"}.get(quiz.category, "❓")

    await message.answer(
        f"{cat_emoji} <b>[{quiz.category}] Вопрос:</b>\n\n{quiz.question}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{i + 1}. {opt}", callback_data=f"qz:{quiz.id}:{i + 1}"
                )]
                for i, opt in enumerate(options)
            ]
        ),
    )


# ─── /top ─────────────────────────────────────────────────────────────────────

@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).order_by(User.score.desc()).limit(5)
        )
        top_users = result.scalars().all()

    if not top_users:
        await message.answer("📭 Рейтинг пока пуст. Первым пройди /quiz!")
        return

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines = ["🏆 <b>ТОП-5 СТУДЕНТОВ OQU+</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"]

    for i, user in enumerate(top_users):
        name = f"@{user.username}" if user.username else user.first_name
        rank_name, _ = _rank_info(user.score)
        streak = f"  🔥{user.streak_count}" if user.streak_count > 1 else ""
        lines.append(f"{medals[i]} {name} — <b>{user.score} pts</b>  <i>{rank_name}</i>{streak}")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /duel ────────────────────────────────────────────────────────────────────

@router.message(Command("duel"))
async def cmd_duel(message: Message) -> None:
    if not message.from_user:
        return

    async with AsyncSessionLocal() as session:
        await _get_or_create_user(session, message.from_user)

        result = await session.execute(select(Quiz).order_by(func.random()).limit(3))
        quizzes = result.scalars().all()

        if len(quizzes) < 3:
            await message.answer("❌ Недостаточно вопросов для дуэли (нужно минимум 3).")
            return

        # Генерируем уникальный код (повтор крайне маловероятен)
        code = _generate_code()
        while await session.scalar(
            select(Duel).where(Duel.code == code, Duel.status == "waiting")
        ):
            code = _generate_code()

        duel = Duel(
            code=code,
            chat_id=message.chat.id,
            challenger_id=message.from_user.id,
            quiz_ids=",".join(str(q.id) for q in quizzes),
        )
        session.add(duel)
        await session.commit()

    await message.answer(
        "⚔️ <b>Дуэль создана!</b>\n\n"
        f"Твой код: <code>{code}</code>\n\n"
        f"Отправь его другу. Пусть напишет:\n"
        f"<code>/join {code}</code>",
        parse_mode="HTML",
    )


# ─── /join ────────────────────────────────────────────────────────────────────

@router.message(Command("join"))
async def cmd_join(message: Message, bot: Bot) -> None:
    if not message.from_user or not message.text:
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.reply("Укажи код дуэли: <code>/join КОД</code>", parse_mode="HTML")
        return

    code = parts[1].upper()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Duel).where(Duel.code == code, Duel.status == "waiting")
        )
        duel = result.scalar_one_or_none()

        if duel is None:
            await message.reply("❌ Дуэль с таким кодом не найдена или уже началась.")
            return

        if duel.challenger_id == message.from_user.id:
            await message.reply("❌ Нельзя принять собственную дуэль.")
            return

        await _get_or_create_user(session, message.from_user)
        duel.opponent_id = message.from_user.id
        duel.status = "active"
        await session.commit()

        await message.answer("⚔️ Дуэль начинается! Отвечайте на вопросы ниже.")
        await _send_duel_question(bot, duel, 0, session)


# ─── /find_buddy ──────────────────────────────────────────────────────────────

_SUBJECTS = [
    ("💻 Python",      "Python"),
    ("📐 Математика",  "Математика"),
    ("🇬🇧 Английский", "Английский"),
    ("⚛️ Физика",      "Физика"),
    ("🧪 Химия",       "Химия"),
    ("🧬 Биология",    "Биология"),
    ("📖 История",     "История"),
    ("💡 Информатика", "Информатика"),
]


@router.message(Command("find_buddy"))
async def cmd_find_buddy(message: Message) -> None:
    await message.answer(
        "🤝 <b>Поиск напарника</b>\n\nЧто ты сейчас изучаешь?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"sb:{value}")]
                for label, value in _SUBJECTS
            ]
        ),
    )


# ─── Callback: задача выполнена ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("done:"))
async def callback_done(call: CallbackQuery) -> None:
    task_id = int(call.data.split(":")[1])

    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if task is None:
            await call.answer("Задача не найдена.", show_alert=True)
            return
        if task.is_done:
            await call.answer("Эта задача уже выполнена.", show_alert=True)
            return

        task.is_done = True
        if call.from_user:
            user = await _get_or_create_user(session, call.from_user)
            user.completed_tasks += 1
            user.score += 5
        await session.commit()

    await call.answer("✅ Выполнено! +5 очков 🎉")
    if call.message:
        await call.message.edit_text(
            f"✅ <b>Задача #{task_id} выполнена!</b>",
            parse_mode="HTML",
        )


# ─── Callback: ответ на квиз ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("qz:"))
async def callback_quiz(call: CallbackQuery) -> None:
    _, quiz_id_str, selected_str = call.data.split(":")
    quiz_id, selected = int(quiz_id_str), int(selected_str)

    async with AsyncSessionLocal() as session:
        quiz = await session.get(Quiz, quiz_id)
        if quiz is None:
            await call.answer("Вопрос не найден.", show_alert=True)
            return

        is_correct = selected == quiz.correct_option
        correct_text = [quiz.option_1, quiz.option_2, quiz.option_3, quiz.option_4][
            quiz.correct_option - 1
        ]
        streak_bonus = 0
        total_score = 0
        streak_count = 0

        if is_correct and call.from_user:
            user = await _get_or_create_user(session, call.from_user)
            streak_count = user.streak_count
            streak_bonus = streak_count * 5
            total_score = 10 + streak_bonus
            user.completed_quizzes += 1
            user.score += total_score
            await session.commit()

    cat_emoji = {"IT": "💻", "English": "🇬🇧", "Math": "📐"}.get(quiz.category, "❓")

    # Отвечаем на callback сразу, чтобы не было таймаута Telegram
    if is_correct:
        bonus_line = (
            f"\n<i>+{streak_bonus} streak бонус 🔥 ({streak_count} дн. подряд)</i>"
            if streak_bonus > 0 else ""
        )
        result_text = f"✅ <b>Правильно! +{total_score} очков</b>{bonus_line}"
        await call.answer(f"Правильно! +{total_score} очков 🎉")
    else:
        await call.answer("Неверно!")
        # Запрашиваем объяснение у Groq (1-2 сек, поэтому после answer)
        wrong_text = [quiz.option_1, quiz.option_2, quiz.option_3, quiz.option_4][selected - 1]
        explanation = await explain_wrong_answer(quiz.question, wrong_text, correct_text)
        explanation_block = f"\n\n💡 <i>{explanation}</i>" if explanation else ""
        result_text = (
            f"❌ <b>Неверно.</b> Правильный ответ: <b>{correct_text}</b>"
            f"{explanation_block}"
        )

    if call.message:
        try:
            await call.message.edit_text(
                f"{cat_emoji} <b>[{quiz.category}]</b> {quiz.question}\n\n"
                f"{result_text}\n\n➡️ Следующий вопрос: /quiz",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ─── Callback: ответ на вопрос дуэли ─────────────────────────────────────────

@router.callback_query(F.data.startswith("dq:"))
async def callback_duel_answer(call: CallbackQuery, bot: Bot) -> None:
    _, duel_id_str, q_idx_str, option_str = call.data.split(":")
    duel_id, q_idx, option = int(duel_id_str), int(q_idx_str), int(option_str)
    user_id = call.from_user.id if call.from_user else None

    if user_id is None:
        return

    async with AsyncSessionLocal() as session:
        duel = await session.get(Duel, duel_id)

        if duel is None or duel.status != "active":
            await call.answer("Дуэль не найдена или уже завершена.", show_alert=True)
            return

        is_challenger = user_id == duel.challenger_id
        is_opponent = user_id == duel.opponent_id

        if not is_challenger and not is_opponent:
            await call.answer("Ты не участвуешь в этой дуэли.", show_alert=True)
            return

        # Проверяем, не ответил ли уже на этот вопрос
        my_progress = duel.challenger_progress if is_challenger else duel.opponent_progress
        if my_progress > q_idx:
            await call.answer("Ты уже ответил на этот вопрос.", show_alert=True)
            return

        quiz_ids = [int(x) for x in duel.quiz_ids.split(",")]
        quiz = await session.get(Quiz, quiz_ids[q_idx])
        is_correct = quiz is not None and option == quiz.correct_option

        if is_challenger:
            if is_correct:
                duel.challenger_score += 1
            duel.challenger_progress += 1
        else:
            if is_correct:
                duel.opponent_score += 1
            duel.opponent_progress += 1

        await call.answer("✅ Правильно!" if is_correct else "❌ Неверно!")

        both_answered = duel.challenger_progress > q_idx and duel.opponent_progress > q_idx

        if both_answered:
            if q_idx < 2:
                await session.commit()
                await _send_duel_question(bot, duel, q_idx + 1, session)
            else:
                duel.status = "finished"
                await _announce_duel_result(bot, duel, session)

        await session.commit()


# ─── Callback: выбор предмета (find_buddy) ────────────────────────────────────

@router.callback_query(F.data.startswith("sb:"))
async def callback_subject(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        return

    subject = call.data.split(":", 1)[1]

    async with AsyncSessionLocal() as session:
        user = await _get_or_create_user(session, call.from_user)
        user.subject = subject

        result = await session.execute(
            select(User)
            .where(User.subject == subject, User.id != call.from_user.id)
            .order_by(User.score.desc())
            .limit(5)
        )
        buddies = result.scalars().all()
        await session.commit()

    if not buddies:
        await call.message.edit_text(
            f"🔍 Ты изучаешь <b>{subject}</b>.\n\n"
            "😔 Пока никто другой не ищет напарника по этому предмету.\n"
            "Попробуй позже или выбери другой: /find_buddy",
            parse_mode="HTML",
        )
        await call.answer()
        return

    lines = [f"🤝 <b>Напарники по предмету {subject}:</b>\n"]
    for buddy in buddies:
        name = f"@{buddy.username}" if buddy.username else buddy.first_name
        rank_name, _ = _rank_info(buddy.score)
        lines.append(f"• {name} — {rank_name} ({buddy.score} pts)")
    lines.append("\n📩 Напиши им напрямую!")

    await call.message.edit_text("\n".join(lines), parse_mode="HTML")
    await call.answer()
