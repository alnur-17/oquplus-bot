import logging

from groq import AsyncGroq

from config import settings

logger = logging.getLogger(__name__)

# ─── Системные промпты ────────────────────────────────────────────────────────

_TUTOR_PROMPT = """Ты — дружелюбный учитель-помощник в Telegram-боте OQU+ для студентов 11 класса.

Правила:
- Отвечай ТОЛЬКО на русском языке
- Максимум 3-4 предложения в ответе
- Объясняй просто, с примерами если нужно
- Задавай наводящий вопрос в конце, чтобы студент думал сам
- Если вопрос не по учёбе — мягко верни к теме учёбы
- НЕ давай готовые ответы на домашние задания сразу"""

_EXPLAIN_PROMPT = "Ты учитель. Отвечай на русском. Максимум 2 предложения."

# ─── Клиент ───────────────────────────────────────────────────────────────────

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq | None:
    """Возвращает Groq-клиент или None если ключ не задан."""
    if not settings.GROQ_API_KEY:
        return None
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


# ─── Публичные функции ────────────────────────────────────────────────────────

async def ask_tutor(question: str) -> str:
    """Отправляет вопрос ИИ-учителю и возвращает ответ."""
    client = _get_client()
    if client is None:
        return "❌ GROQ_API_KEY не настроен. Добавь ключ в файл .env"

    try:
        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": _TUTOR_PROMPT},
                {"role": "user",   "content": question},
            ],
            max_tokens=350,
            temperature=0.7,
        )
        return response.choices[0].message.content or "Не удалось получить ответ."

    except Exception as e:
        logger.error("Groq ask_tutor error: %s", e)
        # Разбираем тип ошибки для понятного сообщения
        msg = str(e).lower()
        if "api_key" in msg or "authentication" in msg:
            return "❌ Неверный GROQ_API_KEY. Проверь ключ на console.groq.com"
        if "rate" in msg or "limit" in msg:
            return "⏳ Превышен лимит запросов Groq. Попробуй через минуту."
        return "❌ Ошибка ИИ. Попробуй позже."


async def explain_wrong_answer(question: str, wrong: str, correct: str) -> str:
    """
    Генерирует краткое объяснение (1-2 предложения), почему ответ неверен.
    Возвращает пустую строку если ключ не задан или произошла ошибка.
    """
    client = _get_client()
    if client is None:
        return ""

    prompt = (
        f"Вопрос: «{question}»\n"
        f"Студент ответил: «{wrong}» — это НЕВЕРНО.\n"
        f"Правильный ответ: «{correct}».\n\n"
        "Объясни в 1-2 предложениях, почему выбранный вариант неверен и в чём суть правильного ответа."
    )

    try:
        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": _EXPLAIN_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=150,
            temperature=0.5,
        )
        return response.choices[0].message.content or ""

    except Exception as e:
        logger.warning("Groq explain error (non-critical): %s", e)
        return ""
