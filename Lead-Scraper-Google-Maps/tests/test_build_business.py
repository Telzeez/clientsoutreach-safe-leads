from geo.models import SearchUnit
from scraper.maps_scraper import _business_from_place, _tile_location_bias
from config.runconfig import RunConfig

UNIT = SearchUnit(
    category="plumbers",
    query="plumbers in Katy, TX, USA",
    city="Austin, TX, USA",
    area="Katy",
    region="TX",
)


def place(**overrides):
    result = {
        "id": "ChIJ123",
        "displayName": {"text": "Beyond Wow Plumbing"},
        "primaryTypeDisplayName": {"text": "Plumber"},
        "formattedAddress": "3432 Greystone Dr, Austin, TX 78731, USA",
        "nationalPhoneNumber": "512-601-6173",
        "internationalPhoneNumber": "+1 512-601-6173",
        "websiteUri": "https://beyondwowplumbing.com",
        "rating": 4.8,
        "userRatingCount": 2546,
        "location": {"latitude": 30.3578911, "longitude": -97.7482485},
        "plusCode": {"globalCode": "8FVC9G8F+6W"},
        "regularOpeningHours": {
            "weekdayDescriptions": ["Monday: 8:00 AM – 5:00 PM"]
        },
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "googleMapsUri": "https://maps.google.com/?cid=123",
    }
    result.update(overrides)
    return result


def test_maps_result_maps_to_export_model():
    business = _business_from_place(place(), UNIT)

    assert business is not None
    assert business.name == "Beyond Wow Plumbing"
    assert business.place_id == "ChIJ123"
    assert business.category == "Plumber"
    assert business.address.startswith("3432 Greystone")
    assert business.phone == "+1 512-601-6173"
    assert business.has_website is True
    assert business.rating == 4.8
    assert business.review_count == 2546
    assert business.latitude == 30.3578911
    assert business.longitude == -97.7482485
    assert business.plus_code == "8FVC9G8F+6W"
    assert business.hours == "Monday: 8:00 AM – 5:00 PM"
    assert business.price_level == "$$"
    assert business.google_maps_url == "https://maps.google.com/?cid=123"
    assert business.city == "Austin, TX, USA"
    assert business.area == "Katy"
    assert business.search_query == UNIT.query


def test_missing_optional_places_fields_are_supported():
    business = _business_from_place(
        place(
            primaryTypeDisplayName=None,
            formattedAddress=None,
            nationalPhoneNumber=None,
            internationalPhoneNumber=None,
            websiteUri=None,
            rating=None,
            userRatingCount=None,
            location=None,
            plusCode=None,
            regularOpeningHours=None,
            priceLevel=None,
            googleMapsUri=None,
        ),
        UNIT,
    )

    assert business is not None
    assert business.phone is None
    assert business.has_website is False
    assert business.rating is None
    assert business.review_count is None
    assert business.google_maps_url.startswith(
        "https://www.google.com/maps/search/?"
    )


def test_places_without_identity_or_name_are_rejected():
    assert _business_from_place(place(id=None), UNIT) is None
    assert _business_from_place(place(displayName=None), UNIT) is None
    assert _business_from_place(place(displayName={"text": " "}), UNIT) is None


def test_grid_units_get_a_bounded_location_bias():
    unit = SearchUnit(
        category="plumbers",
        query="plumbers in Austin TX",
        city="Austin TX",
        lat=30.0,
        lng=-97.0,
        tile="r1c1",
    )

    bias = _tile_location_bias(
        unit, RunConfig(grid_span_km=18, grid_rows=3, grid_cols=3)
    )
    assert bias["circle"]["center"] == {"latitude": 30.0, "longitude": -97.0}
    assert bias["circle"]["radius"] == 18_000 / 3 / 2**0.5
    assert _tile_location_bias(UNIT, RunConfig()) is None
