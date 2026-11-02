"""Search Google Places and optionally enrich results from business websites."""

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode

from playwright.async_api import Page

from config import settings
from config.runconfig import RunConfig
from data.models import Business
from geo.models import SearchUnit
from scraper.extract import extract_website_contacts
from scraper.google_places import GoogleMapsAPIError, GoogleMapsClient
from scraper.parsers import (
    collect_socials,
    contact_page_urls,
    email_from_mailto,
    find_emails,
    is_valid_email,
    normalize_website,
)

logger = logging.getLogger(__name__)

PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


@dataclass
class UnitResult:
    """Outcome of searching one SearchUnit."""

    businesses: list[Business] = field(default_factory=list)
    processed: set[str] = field(default_factory=set)
    total_cards: int = 0

    @property
    def found(self) -> int:
        return len(self.businesses)


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("text")
    if isinstance(value, str):
        return value.strip() or None
    return None


def _business_from_place(place: dict, unit: SearchUnit) -> Business | None:
    """Map a Places API result to the export model."""
    name = _text(place.get("displayName"))
    place_id = place.get("id")
    if not name or not isinstance(place_id, str) or not place_id:
        return None

    location = place.get("location") or {}
    plus_code = place.get("plusCode") or {}
    opening_hours = place.get("regularOpeningHours") or {}
    weekday_descriptions = opening_hours.get("weekdayDescriptions") or []
    primary_type = _text(place.get("primaryTypeDisplayName"))
    website_url = normalize_website(place.get("websiteUri"))
    maps_url = place.get("googleMapsUri")
    if not maps_url:
        maps_url = (
            "https://www.google.com/maps/search/?"
            + urlencode({"api": "1", "query_place_id": place_id})
        )

    return Business(
        name=name,
        place_id=place_id,
        category=primary_type or place.get("primaryType"),
        address=place.get("formattedAddress"),
        phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
        has_website=bool(website_url),
        website_url=website_url,
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        plus_code=plus_code.get("globalCode"),
        hours="; ".join(weekday_descriptions) if weekday_descriptions else None,
        price_level=PRICE_LEVELS.get(place.get("priceLevel")),
        google_maps_url=maps_url,
        city=unit.city,
        area=unit.area,
        metro_area=unit.city,
        state=unit.region,
        search_query=unit.query,
    )


async def _scrape_website_inner(
    page: Page, website_url: str
) -> tuple[str | None, dict[str, str]]:
    email: str | None = None
    socials: dict[str, str] = {}
    new_page = None
    try:
        new_page = await page.context.new_page()
        new_page.set_default_timeout(settings.WEBSITE_TIMEOUT_MS)
        new_page.set_default_navigation_timeout(settings.WEBSITE_TIMEOUT_MS)
        targets = [website_url] + contact_page_urls(website_url, limit=2)

        for index, url in enumerate(targets):
            try:
                await new_page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.WEBSITE_TIMEOUT_MS,
                )
            except Exception as exc:
                logger.debug("Website fetch failed for %s: %s", url, exc)
                continue

            data = await extract_website_contacts(new_page)
            for href in data.get("emails", []):
                email = email_from_mailto(href)
                if email:
                    break
            if not email:
                candidates = find_emails(data.get("text", ""))
                if candidates:
                    email = candidates[0]

            for network, social_url in collect_socials(data.get("links", [])).items():
                socials.setdefault(network, social_url)

            if email and socials:
                break
            if email and index == 0:
                break
    finally:
        if new_page:
            await new_page.close()

    return email, socials


async def _scrape_website(
    page: Page, website_url: str
) -> tuple[str | None, dict[str, str]]:
    budget = (settings.WEBSITE_TIMEOUT_MS / 1000.0) * 3 + 10.0
    try:
        return await asyncio.wait_for(
            _scrape_website_inner(page, website_url), timeout=budget
        )
    except asyncio.TimeoutError:
        logger.debug("Website contact lookup timed out: %s", website_url)
    except Exception as exc:
        logger.debug("Website contact lookup failed for %s: %s", website_url, exc)
    return None, {}


def _tile_location_bias(unit: SearchUnit, cfg: RunConfig) -> dict | None:
    if unit.lat is None or unit.lng is None:
        return None
    cell_km = cfg.grid_span_km / max(1, cfg.grid_rows, cfg.grid_cols)
    radius = min(50_000.0, cell_km * 1000 / 2**0.5)
    return {
        "circle": {
            "center": {"latitude": unit.lat, "longitude": unit.lng},
            "radius": max(1.0, radius),
        }
    }


async def search_and_scrape(
    page: Page | None,
    unit: SearchUnit,
    cfg: RunConfig,
    *,
    maps_api: GoogleMapsClient | None = None,
    on_business=None,
    on_progress=None,
    on_processed=None,
    skip_hrefs: set[str] | None = None,
) -> UnitResult:
    """Search Places API and map its JSON results into Businesses.

    ``page`` is only used for optional contact discovery on business websites;
    Google Maps data is always obtained from the official API.
    """
    result = UnitResult()
    skipped = skip_hrefs or set()
    client = maps_api or GoogleMapsClient()
    logger.info("Searching Places API: %s", unit.query)

    places = await client.search_text(
        unit.query,
        location_bias=_tile_location_bias(unit, cfg),
        max_results=(
            cfg.max_results_per_unit
            if cfg.max_results_per_unit and cfg.max_results_per_unit > 0
            else None
        ),
    )
    result.total_cards = len(places)
    pending = [
        place for place in places
        if isinstance(place.get("id"), str) and place["id"] not in skipped
    ]

    for index, place in enumerate(pending, start=1):
        place_id = place["id"]
        business = _business_from_place(place, unit)
        if business is None:
            raise GoogleMapsAPIError(
                "Places API returned a result without a usable display name."
            )
        if cfg.crawl_websites and business.website_url:
            if page is None:
                raise RuntimeError(
                    "Website contact discovery is enabled but no browser page is available."
                )
            email, socials = await _scrape_website(page, business.website_url)
            if email and is_valid_email(email):
                business.email = email
            business.facebook = socials.get("facebook")
            business.instagram = socials.get("instagram")
            business.linkedin = socials.get("linkedin")

        result.processed.add(place_id)
        if on_processed:
            on_processed(place_id)
        result.businesses.append(business)
        if on_business:
            on_business(business)
        if on_progress:
            on_progress(index, len(pending))

    logger.info("Found %s Places API results for '%s'", result.found, unit.query)
    return result
