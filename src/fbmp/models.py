from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "medium", "high"]
CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


class Listing(BaseModel):
    id: str
    title: str
    price: float  # 0.0 for "Free"
    location: str = ""
    image_url: str | None = None
    page_text: str = ""  # visible text of the detail page, filled in after triage
    photo_urls: list[str] = Field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.facebook.com/marketplace/item/{self.id}/"


class Comp(BaseModel):
    """One eBay listing used as a price comparison."""

    title: str
    price: float
    shipping: float = 0.0
    condition: str = ""
    url: str = ""

    @property
    def total(self) -> float:
        return self.price + self.shipping


# --- Claude structured outputs ---------------------------------------------


class TriageItem(BaseModel):
    id: str = Field(description="The listing id, copied exactly from the input.")
    keep: bool = Field(description="True if this listing is worth a closer look as a flip.")
    product: str = Field(description="Most specific product name: brand, model, variant. Empty if rejected.")
    ebay_query: str = Field(description="3-6 word eBay search query for the same product. Empty if rejected.")
    reason: str = Field(description="One short phrase explaining the decision.")


class TriageResult(BaseModel):
    items: list[TriageItem]


class Valuation(BaseModel):
    product: str = Field(description="The exact product identified, e.g. 'DeWalt DCD791D2 20V drill kit'.")
    matching_comps: list[int] = Field(description="Numbers of the eBay listings that match this product and condition.")
    condition: Literal["new", "like_new", "good", "fair", "poor", "for_parts", "unknown"]
    shipping_estimate: float = Field(description="Estimated USD cost for the seller to ship this item to an eBay buyer.")
    confidence: Confidence
    red_flags: list[str] = Field(description="Problems that reduce resale value or suggest a scam. Empty if none.")
    summary: str = Field(description="One or two sentences on why this is or is not a good flip.")


# --- Result ------------------------------------------------------------------


class Deal(BaseModel):
    listing: Listing
    valuation: Valuation
    comps: list[Comp]  # only the comps Claude matched
    resale: float  # estimated eBay sale price
    net: float  # resale after fees and shipping
    profit: float
    margin: float | None  # profit / asking price; None when the item is free
