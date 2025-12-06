from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📌 Подписаться"), KeyboardButton(text="📃 Мои подписки")],
        [KeyboardButton(text="🔥 Что в тренде"), KeyboardButton(text="🌐 Язык")]
    ],
    resize_keyboard=True
)

notify_inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Каждый час", callback_data="mode:hourly"),
            InlineKeyboardButton(text="💸 Только при скидке", callback_data="mode:discount")
        ]
    ]
)

def subscription_controls_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Каждый час", callback_data=f"mode:{sub_id}:hourly"),
            InlineKeyboardButton(text="💸 Только при скидке", callback_data=f"mode:{sub_id}:discount")
        ],
        [
            InlineKeyboardButton(text="❌ Отписаться", callback_data=f"unsubscribe:{sub_id}")
        ]
    ])