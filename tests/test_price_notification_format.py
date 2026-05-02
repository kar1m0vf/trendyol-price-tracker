import pytest


def test_price_notification_payload_uses_product_context():
    from bot import build_price_notification_payload

    url = "https://www.trendyol.com/example/product-p-123.html"
    payload = build_price_notification_payload(
        12345,
        reason="discount_drop",
        sub_id=42,
        url=url,
        title="Roborock Q8 Smart Robot Vacuum",
        image="https://example.com/image.jpg",
        current_price=8999,
        old_price=9999,
        percent=-10.0,
    )

    assert payload["parse_mode"] == "HTML"
    assert "Roborock Q8 Smart Robot Vacuum" in payload["text"]
    assert url not in payload["text"]
    assert "8999 TL" in payload["text"]
    assert "9999 TL" in payload["text"]
    assert "-10.0%" in payload["text"]

    keyboard = payload["reply_markup"].inline_keyboard
    assert keyboard[0][0].url == url
    assert any(button.callback_data == "history:42" for row in keyboard for button in row)
    assert any(button.callback_data == "edit_sub:42" for row in keyboard for button in row)


@pytest.mark.asyncio
async def test_grouped_price_notifications_use_summaries(monkeypatch):
    import bot

    url_a = "https://www.trendyol.com/example/a-p-1.html"
    url_b = "https://www.trendyol.com/example/b-p-2.html"
    payload_a = bot.build_price_notification_payload(
        12345,
        reason="discount_drop",
        sub_id=1,
        url=url_a,
        title="Product A",
        image=None,
        current_price=900,
        old_price=1000,
        percent=-10.0,
    )
    payload_b = bot.build_price_notification_payload(
        12345,
        reason="percent_increase",
        sub_id=2,
        url=url_b,
        title="Product B",
        image=None,
        current_price=1100,
        old_price=1000,
        percent=10.0,
    )

    sent = []

    async def fake_send(user_id, text, image=None, timeout=10.0, parse_mode=None, reply_markup=None):
        sent.append(
            {
                "user_id": user_id,
                "text": text,
                "image": image,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        return True

    monkeypatch.setattr(bot, "send_notification_with_timeout", fake_send)

    await bot.send_grouped_notifications({12345: [payload_a, payload_b]})

    assert len(sent) == 1
    assert sent[0]["parse_mode"] == "HTML"
    assert sent[0]["image"] is None
    assert sent[0]["reply_markup"] is not None
    assert "Product A" in sent[0]["text"]
    assert "Product B" in sent[0]["text"]
    assert url_a not in sent[0]["text"]
    assert url_b not in sent[0]["text"]
