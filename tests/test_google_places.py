import asyncio
from copy import deepcopy

import pytest

from config import settings
from config.runconfig import RunConfig
from geo.models import SearchUnit
from geo.resolver import resolve_target
from scraper.google_places import (
    PLACES_FIELD_MASK,
    PLACES_SEARCH_URL,
    GoogleMapsAPIError,
    GoogleMapsClient,
)
from scraper.maps_scraper import search_and_scrape


def test_missing_key_fails_with_setup_instructions(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", None)
    with pytest.raises(GoogleMapsAPIError, match="SCRAPER_GOOGLE_MAPS_API_KEY"):
        GoogleMapsClient()


def test_text_search_posts_json_and_follows_pages(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")
    calls = []

    async def fake_request(url, **kwargs):
        calls.append((url, deepcopy(kwargs)))
        if len(calls) == 1:
            return {
                "places": [{"id": f"place-{i}"} for i in range(20)],
                "nextPageToken": "token-2",
            }
        return {"places": [{"id": f"place-{i}"} for i in range(20, 30)]}

    monkeypatch.setattr(client, "_request", fake_request)
    places = asyncio.run(client.search_text("plumbers in Austin TX", max_results=25))

    assert len(places) == 25
    assert calls[0][0] == PLACES_SEARCH_URL
    assert calls[0][1]["body"] == {
        "textQuery": "plumbers in Austin TX",
        "pageSize": 20,
    }
    assert calls[0][1]["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "places.displayName" in calls[0][1]["headers"]["X-Goog-FieldMask"]
    assert calls[1][1]["body"]["pageToken"] == "token-2"
    assert "nextPageToken" in PLACES_FIELD_MASK


def test_text_search_stops_at_three_pages():
    client = GoogleMapsClient(api_key="test-key")
    calls = []

    async def fake_request(url, **kwargs):
        calls.append(kwargs["body"].copy())
        return {
            "places": [{"id": f"place-{len(calls)}"}],
            "nextPageToken": f"token-{len(calls)}",
        }

    client._request = fake_request
    places = asyncio.run(client.search_text("dentists"))

    assert len(places) == 3
    assert len(calls) == 3


def test_text_search_rejects_results_without_a_place_id(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")

    async def fake_request(url, **kwargs):
        return {"places": [{"displayName": {"text": "No ID"}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(GoogleMapsAPIError, match="without a place ID"):
        asyncio.run(client.search_text("plumbers"))


def test_non_positive_result_cap_does_not_make_a_request(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")

    async def unexpected_request(*args, **kwargs):
        raise AssertionError("request should not be made")

    monkeypatch.setattr(client, "_request", unexpected_request)
    assert asyncio.run(client.search_text("dentists", max_results=0)) == []


def test_geocoding_zero_results_is_not_treated_as_an_api_failure(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")

    async def fake_request(url, **kwargs):
        assert url.startswith("https://maps.googleapis.com/maps/api/geocode/json?")
        assert "address=New+Place" in url
        return {"status": "ZERO_RESULTS", "results": []}

    monkeypatch.setattr(client, "_request", fake_request)
    assert asyncio.run(client.geocode("New Place")) is None


def test_geocoding_api_errors_are_reported(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")

    async def fake_request(url, **kwargs):
        return {"status": "REQUEST_DENIED", "error_message": "API not enabled"}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(GoogleMapsAPIError, match="API not enabled"):
        asyncio.run(client.geocode("Austin TX"))


def test_target_resolution_uses_geocoded_address_and_coordinates():
    class FakeClient:
        async def geocode(self, address):
            assert address == "Austin TX"
            return {
                "formatted_address": "Austin, TX, USA",
                "geometry": {"location": {"lat": 30.2672, "lng": -97.7431}},
            }

    target = asyncio.run(resolve_target(FakeClient(), "Austin TX"))

    assert target.query == "Austin, TX, USA"
    assert target.lat == 30.2672
    assert target.lng == -97.7431
    assert target.region == "TX"


def test_search_returns_places_and_emits_progress_callbacks():
    place = {
        "id": "place-1",
        "displayName": {"text": "Austin Plumbing"},
        "formattedAddress": "Austin, TX",
    }

    class FakeClient:
        async def search_text(self, query, **kwargs):
            assert query == "plumbers in Austin TX"
            assert kwargs["max_results"] == 10
            return [place]

    unit = SearchUnit(
        category="plumbers",
        query="plumbers in Austin TX",
        city="Austin TX",
    )
    businesses = []
    processed = []
    progress = []
    result = asyncio.run(search_and_scrape(
        None,
        unit,
        RunConfig(
            target_input="Austin TX",
            fetch_website_email=False,
            max_results_per_unit=10,
        ),
        maps_api=FakeClient(),
        on_business=businesses.append,
        on_processed=processed.append,
        on_progress=lambda done, total: progress.append((done, total)),
    ))

    assert result.found == 1
    assert result.total_cards == 1
    assert result.processed == {"place-1"}
    assert businesses[0].name == "Austin Plumbing"
    assert processed == ["place-1"]
    assert progress == [(1, 1)]


def test_transient_api_errors_are_retried(monkeypatch):
    client = GoogleMapsClient(api_key="test-key")
    monkeypatch.setattr(settings, "RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0)
    calls = []

    def fake_request_sync(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise GoogleMapsAPIError("temporary", retryable=True)
        return {"ok": True}

    monkeypatch.setattr(client, "_request_sync", fake_request_sync)
    assert asyncio.run(client._request("https://example.test")) == {"ok": True}
    assert len(calls) == 2
