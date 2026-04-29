"""Keyboard utilities and markup generators."""

from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from localization import t as translate_func
import logging

logger = logging.getLogger(__name__)


def get_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    """Return the main reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=translate_func(user_id, "btn_subscribe")),
                KeyboardButton(text=translate_func(user_id, "btn_subs")),
            ],
            [
                KeyboardButton(text=translate_func(user_id, "btn_trending")),
                KeyboardButton(text=translate_func(user_id, "btn_recommend")),
            ],
            [
                KeyboardButton(text=translate_func(user_id, "btn_language")),
                KeyboardButton(text=translate_func(user_id, "btn_help")),
            ],
        ],
        resize_keyboard=True,
    )


def get_notify_inline_kb(
    user_id: int, sub_id: Optional[int] = None
) -> InlineKeyboardMarkup:
    """Return notification mode selection keyboard."""
    if sub_id:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=translate_func(user_id, "btn_mode_discount"),
                        callback_data=f"mode:{sub_id}:discount",
                    ),
                    InlineKeyboardButton(
                        text=translate_func(user_id, "btn_mode_hourly"),
                        callback_data=f"mode:{sub_id}:hourly",
                    ),
                ]
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_mode_discount"),
                    callback_data="mode:discount",
                ),
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_mode_hourly"),
                    callback_data="mode:hourly",
                ),
            ]
        ]
    )


def subscription_controls_kb_for_user(
    user_id: int, sub_id: int
) -> InlineKeyboardMarkup:
    """Return per-subscription controls keyboard."""
    from database import get_subscription

    mode_label_hourly = translate_func(user_id, "btn_mode_hourly")
    mode_label_discount = translate_func(user_id, "btn_mode_discount")

    try:
        sub = get_subscription(sub_id)
        if sub:
            try:
                mode_db = sub[3]
            except Exception as exc:
                logger.exception(
                    "Failed to read mode for subscription %s: %s", sub_id, exc
                )
                mode_db = None

            if mode_db == "hourly":
                mode_label_hourly = "✅ " + mode_label_hourly
            elif mode_db == "discount":
                mode_label_discount = "✅ " + mode_label_discount
    except Exception as exc:
        logger.exception(
            "Error while building subscription controls keyboard for sub %s: %s",
            sub_id,
            exc,
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=mode_label_discount, callback_data=f"mode:{sub_id}:discount"
                ),
                InlineKeyboardButton(
                    text=mode_label_hourly, callback_data=f"mode:{sub_id}:hourly"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_history"),
                    callback_data=f"history:{sub_id}",
                ),
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_price_alert"),
                    callback_data=f"alert_edit:{sub_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_compare"),
                    callback_data=f"compare:{sub_id}",
                ),
                InlineKeyboardButton(
                    text=translate_func(user_id, "btn_unsubscribe_inline"),
                    callback_data=f"unsubscribe:{sub_id}",
                )
            ],
        ]
    )
