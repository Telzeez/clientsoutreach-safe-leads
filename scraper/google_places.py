"""Small async client for Google's Places API (New) and Geocoding API."""

import asyncio
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_FIELD_MASK = ",".join((
    "places.id",
    "places.displayName",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.location",
    "places.plusCode",
    "places.regularOpeningHours.weekdayDescriptions",
    "places.priceLevel",
    "places.googleMapsUri",
    "nextPageToken",
))
MAX_TEXT_SEARCH_PAGES = 3
PAGE_SIZE = 20


class GoogleMapsAPIError(RuntimeError):
    """A Google Maps Platform request failed."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class GoogleMapsClient:
    """Call Google Maps Platform REST endpoints without browser scraping."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GOOGLE_MAPS_API_KEY
        if not self.api_key:
            raise GoogleMapsAPIError(
                "Google Maps API key is required. Set "
                "SCRAPER_GOOGLE_MAPS_API_KEY and enable Places API (New) and "
                "Geocoding API for a billing-enabled Google Cloud project."
            )

    @staticmethod
    def _decode_json(payload: bytes) -> dict:
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleMapsAPIError(
                "Google Maps Platform returned an invalid JSON response."
            ) from exc
        if not isinstance(value, dict):
            raise GoogleMapsAPIError(
                "Google Maps Platform returned an unexpected JSON response."
            )
        return value

    def _request_sync(
        self,
        url: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        request_headers = {"Accept": "application/json"}
        request_headers.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=request_headers)

        try:
            with urlopen(request, timeout=30) as response:
                return self._decode_json(response.read())
        except HTTPError as exc:
            payload = self._decode_json(exc.read())
            error = payload.get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
            raise GoogleMapsAPIError(
                message or f"Google Maps Platform returned HTTP {exc.code}.",
                retryable=exc.code in (429, 500, 502, 503, 504),
            ) from None
        except URLError as exc:
            raise GoogleMapsAPIError(
                f"Could not reach Google Maps Platform: {exc.reason}",
                retryable=True,
            ) from None
        except TimeoutError:
            raise GoogleMapsAPIError(
                "Google Maps Platform request timed out.", retryable=True
            ) from None

    async def _request(self, url: str, **kwargs) -> dict:
        attempts = max(1, settings.RETRY_ATTEMPTS)
        for attempt in range(attempts):
            try:
                return await asyncio.to_thread(self._request_sync, url, **kwargs)
            except GoogleMapsAPIError as exc:
                if not exc.retryable or attempt + 1 == attempts:
                    raise
                delay = settings.RETRY_BASE_DELAY * (settings.RETRY_FACTOR ** attempt)
                logger.warning(
                    "Temporary Google Maps API error; retrying in %.1f seconds.",
                    delay,
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def geocode(self, address: str) -> dict | None:
        """Resolve an address-like target to one Google Geocoding result."""
        query = urlencode({"address": address, "key": self.api_key})
        response = await self._request(f"{GEOCODING_URL}?{query}")
        status = response.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            message = response.get("error_message") or f"Geocoding API status: {status}"
            raise GoogleMapsAPIError(str(message))
        results = response.get("results")
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        return first if isinstance(first, dict) else None

    async def search_text(
        self,
        query: str,
        *,
        location_bias: dict | None = None,
        max_results: int | None = None,
    ) -> list[dict]:
        """Search Places Text Search, following its available page tokens."""
        if max_results is not None and max_results <= 0:
            return []

        body: dict = {"textQuery": query, "pageSize": PAGE_SIZE}
        if location_bias:
            body["locationBias"] = location_bias

        places: list[dict] = []
        seen_tokens: set[str] = set()
        for _ in range(MAX_TEXT_SEARCH_PAGES):
            response = await self._request(
                PLACES_SEARCH_URL,
                body=body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": PLACES_FIELD_MASK,
                },
            )
            page = response.get("places", [])
            if not isinstance(page, list):
                raise GoogleMapsAPIError(
                    "Places API returned an invalid places collection."
                )
            for place in page:
                if (
                    not isinstance(place, dict)
                    or not isinstance(place.get("id"), str)
                    or not place["id"]
                ):
                    raise GoogleMapsAPIError(
                        "Places API returned a result without a place ID."
                    )
                places.append(place)
            if max_results is not None and len(places) >= max_results:
                return places[:max_results]

            token = response.get("nextPageToken")
            if not isinstance(token, str) or not token or token in seen_tokens:
                break
            seen_tokens.add(token)
            body["pageToken"] = token

        return places
