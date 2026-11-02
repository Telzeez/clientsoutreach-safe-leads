"""Resolve targets and discover sub-areas through Google Maps Platform APIs."""

import logging

from config.runconfig import RunConfig
from data.normalize import address_parts, collapse
from geo.areas import rank_subareas
from geo.models import SearchUnit, Target
from geo.plan import build_query
from scraper.google_places import GoogleMapsClient

logger = logging.getLogger(__name__)

_COUNTRY_HINTS = {
    "usa", "united states", "uk", "united kingdom", "canada", "australia",
    "pakistan", "india", "ireland", "new zealand", "south africa",
}


async def resolve_target(client: GoogleMapsClient, raw_input: str) -> Target:
    """Resolve a typed target using the Google Geocoding API."""
    raw_input = raw_input.strip()
    result = await client.geocode(raw_input)
    if result is None:
        logger.warning(
            "Geocoding found no result for '%s'; continuing with the typed target.",
            raw_input,
        )
        return Target(raw=raw_input, display_name=raw_input)

    location = result.get("geometry", {}).get("location", {})
    lat, lng = location.get("lat"), location.get("lng")
    display = result.get("formatted_address") or raw_input
    target = Target(
        raw=raw_input,
        display_name=display,
        lat=lat,
        lng=lng,
        region=_region_from_input(display),
    )
    if target.has_coords:
        logger.info(
            "Resolved '%s' -> %s @ %.4f,%.4f",
            raw_input,
            target.query,
            target.lat,
            target.lng,
        )
    else:
        logger.warning(
            "Geocoding returned no coordinates for '%s'; grid depth unavailable.",
            raw_input,
        )
    return target


def _region_from_input(text: str) -> str | None:
    """Best-effort state/province from a formatted address."""
    parts = address_parts(text)
    if len(parts) >= 2:
        tail = parts[-1].strip()
        if collapse(tail) in _COUNTRY_HINTS and len(parts) >= 3:
            tail = parts[-2].strip()
        if 2 <= len(tail) <= 20 and collapse(tail) not in _COUNTRY_HINTS:
            return tail
    tokens = text.split()
    if len(tokens) >= 2 and len(tokens[-1]) == 2 and tokens[-1].isupper():
        return tokens[-1]
    return None


async def discover_subareas(
    client: GoogleMapsClient,
    target: Target,
    cfg: RunConfig,
    probe_category: str,
    on_business=None,
    probe_limit: int = 40,
) -> tuple[list[str], list]:
    """Rank sub-areas from addresses in a capped Places Text Search."""
    from scraper.maps_scraper import search_and_scrape

    probe_unit = SearchUnit(
        category=probe_category,
        query=build_query(probe_category, target.query),
        city=target.query,
        region=target.region,
    )
    probe_cfg = RunConfig(
        target_input=cfg.target_input,
        profile=cfg.profile,
        min_rating=cfg.min_rating,
        min_reviews=cfg.min_reviews,
        require_phone=cfg.require_phone,
        fetch_website_email=False,
        max_results_per_unit=probe_limit,
        output=cfg.output,
    )

    logger.info("Probing '%s' to discover sub-areas...", probe_unit.query)
    result = await search_and_scrape(
        None, probe_unit, probe_cfg, maps_api=client, on_business=on_business
    )
    addresses = [business.address for business in result.businesses if business.address]
    if not addresses:
        logger.warning("Area probe found no addresses; sub-area discovery unavailable.")
        return [], result.businesses

    areas = rank_subareas(
        addresses,
        city=target.query,
        region=target.region or "",
        max_areas=cfg.max_subareas,
    )
    logger.info(
        "Discovered %s sub-areas from %s addresses: %s%s",
        len(areas),
        len(addresses),
        ", ".join(areas[:8]),
        "..." if len(areas) > 8 else "",
    )
    return areas, result.businesses
