"""
Service for handling notifications and alerts.
"""
import asyncio
import logging
import os
from typing import Optional, List, Tuple, Union, Any
from datetime import datetime

from aiogram import Bot
from aiogram.types import BufferedInputFile
import aiogram.exceptions

from database import get_user_language
from utils import parse_date_flexible

os.environ.setdefault("MPLBACKEND", "Agg")

logger = logging.getLogger(__name__)

class NotificationService:
    """Service for sending notifications with proper error handling and fallbacks."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_notification_safe(
        self,
        user_id: int,
        text: str,
        image: Optional[str] = None,
        timeout_seconds: float = 10.0,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Any] = None,
    ) -> bool:
        """
        Безопасно отправляет уведомление с таймаутом.
        Имеет fallback на текстовое сообщение если фото не отправляется.

        Args:
            user_id: ID получателя
            text: Основной текст сообщения
            image: URL изображения (опционально)
            timeout_seconds: Таймаут в секундах

        Returns:
            True если успешно отправлено, False если ошибка
        """
        try:
            if image:
                try:
                    await asyncio.wait_for(
                        self.bot.send_photo(
                            user_id,
                            photo=image,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup,
                        ),
                        timeout=timeout_seconds
                    )
                    logger.debug(f"Photo notification sent to {user_id}")
                    return True
                except asyncio.TimeoutError:
                    logger.warning(f"Photo send timeout for user {user_id}, falling back to text")
                                                                
                    try:
                        await asyncio.wait_for(
                            self.bot.send_message(
                                user_id,
                                text,
                                parse_mode=parse_mode,
                                reply_markup=reply_markup,
                            ),
                            timeout=timeout_seconds
                        )
                        return True
                    except Exception as e:
                        logger.exception(f"Fallback text message failed for {user_id}: {e}")
                        return False
            else:
                await asyncio.wait_for(
                    self.bot.send_message(
                        user_id,
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    ),
                    timeout=timeout_seconds
                )
                logger.debug(f"Text notification sent to {user_id}")
                return True

        except asyncio.TimeoutError:
            logger.error(f"Notification timeout for user {user_id}")
            return False
        except aiogram.exceptions.TelegramForbiddenError:
            logger.warning(f"User {user_id} blocked the bot")
            return False
        except aiogram.exceptions.TelegramBadRequest as e:
            logger.warning(f"Bad request for user {user_id}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending notification to {user_id}: {e}")
            return False

    async def send_history_plot(
        self,
        user_id: int,
        url: str,
        hist: List[Tuple[Union[str, datetime], float]]
    ) -> bool:
        """Send history plot for a product."""
        try:
            import matplotlib
            import matplotlib.dates as mdates
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.figure import Figure
            from matplotlib.ticker import FuncFormatter
            from io import BytesIO

            matplotlib.use("Agg", force=True)

                                  
            processed = []
            for d, p in hist:
                parsed_dt = None
                if isinstance(d, str):
                    parsed_dt = parse_date_flexible(d)
                elif isinstance(d, datetime):
                    parsed_dt = d

                if parsed_dt:
                    processed.append((parsed_dt, float(p)))
                else:
                    logger.debug(f"Could not parse date for history: {d}")
                    processed.append((d, float(p)))

                                      
            try:
                processed.sort(key=lambda x: x[0] if isinstance(x[0], datetime) else str(x[0]))
            except Exception:
                pass                                                 

            if len(processed) < 2:
                lang = get_user_language(user_id) or "ru"
                error_msg = {
                    "ru": "Недостаточно данных для построения графика",
                    "en": "Not enough data to build a chart",
                    "az": "Qrafik qurmaq üçün kifayət qədər məlumat yoxdur",
                    "tr": "Grafik oluşturmak için yeterli veri yok"
                }.get(lang, "Not enough data to build a chart")

                await self.bot.send_message(user_id, error_msg)
                return True

                         
            fig = Figure(figsize=(10, 6))
            FigureCanvasAgg(fig)
            ax = fig.subplots()

                                                     
            datetime_data = [(d, p) for d, p in processed if isinstance(d, datetime)]
            non_datetime_data = [(d, p) for d, p in processed if not isinstance(d, datetime)]

            if datetime_data:
                dates, prices = zip(*datetime_data)
                ax.plot(dates, prices, 'b-o', linewidth=2, markersize=4)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))
                for label in ax.xaxis.get_majorticklabels():
                    label.set_rotation(45)
            else:
                                                
                indices = list(range(len(non_datetime_data)))
                prices = [p for _, p in non_datetime_data]
                ax.plot(indices, prices, 'b-o', linewidth=2, markersize=4)

            ax.set_title(f'Price History\n{url[:50]}...', fontsize=12, pad=20)
            ax.set_ylabel('Price (TL)', fontsize=10)
            ax.set_xlabel('Date', fontsize=10)
            ax.grid(True, alpha=0.3)

                                 
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.0f}'))

            fig.tight_layout()

                            
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            image = BufferedInputFile(buf.getvalue(), filename="price_history.png")
            fig.clear()

                       
            await self.bot.send_photo(
                user_id,
                photo=image,
                caption=f"📊 Price history for {url[:50]}..."
            )
            return True

        except ImportError:
                                                     
            lang = get_user_language(user_id) or "ru"
            fallback_msg = {
                "ru": "Matplotlib не установлен. Невозможно построить график.",
                "en": "Matplotlib is not installed. Cannot build chart.",
                "az": "Matplotlib quraşdırılmayıb. Qrafik qurmaq mümkün deyil.",
                "tr": "Matplotlib kurulmamış. Grafik oluşturulamıyor."
            }.get(lang, "Matplotlib is not installed. Cannot build chart.")

            try:
                await self.bot.send_message(user_id, fallback_msg)
                return True
            except Exception:
                logger.exception("Failed to send history plot ImportError fallback to %s", user_id)
                return False

        except Exception as e:
            logger.exception(f"Error creating history plot for user {user_id}: {e}")
            lang = get_user_language(user_id) or "ru"
            error_msg = {
                "ru": "Ошибка при создании графика",
                "en": "Error creating chart",
                "az": "Qrafik yaradılarkən xəta",
                "tr": "Grafik oluşturulurken hata"
            }.get(lang, "Error creating chart")
            try:
                await self.bot.send_message(user_id, error_msg)
                return True
            except Exception:
                logger.exception("Failed to send history plot error fallback to %s", user_id)
                return False












