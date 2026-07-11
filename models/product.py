"""Canonical product data shared by scraper, scheduler, and presenters."""

from dataclasses import dataclass, field
import time
from typing import Mapping, Optional


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    """One observed state of a product.

    Only ``url`` is structural. Other fields are optional so the scraper can
    grow without forcing every caller or every Trendyol response to provide
    the complete product shape immediately.
    """

    price: Optional[float] = None
    title: Optional[str] = None
    image: Optional[str] = None
    # Keep the original positional order (price, title, image) used by the
    # scraper while adding URL as the first new optional field.
    url: str = ""
    product_id: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    old_price: Optional[float] = None
    discount_percent: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    seller: Optional[str] = None
    delivery: Optional[str] = None
    attributes: Mapping[str, str] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    source: str = "trendyol"

    @property
    def current_price(self) -> Optional[float]:
        """Semantic alias used by future card and recommendation presenters."""
        return self.price

    @property
    def has_core_data(self) -> bool:
        """Return whether the snapshot contains useful product information."""
        return self.price is not None or bool(self.title or self.image)
