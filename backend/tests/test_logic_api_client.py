import asyncio
from datetime import date

import httpx
import pytest

from app.logic_api.client import LogicApiClient
from app.logic_api.adapter import adapt_room
from app.logic_api.errors import (
    LogicApiProtocolError,
    LogicApiUnavailable,
    LogicConflict,
    LogicDayClosed,
    LogicInvalidRequest,
    LogicOpeningHoursMissing,
)


def make_client(handler, *, ttl: int = 3600, timeout: float = 3.0):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LogicApiClient(
        "https://logic.test",
        timeout_seconds=timeout,
        cache_ttl_seconds=ttl,
        http_client=http,
    ), http


def test_reads_all_documented_endpoints_and_returns_typed_models():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/rates":
            return httpx.Response(200, json=[{
                "id": 8, "day_type": "weekend", "day_label": "Fin de semana",
                "day_range": None, "players": 4, "price_per_person": 50000,
                "currency": "COP", "internal_cost": 123,
            }])
        if request.url.path == "/api/rooms":
            return httpx.Response(200, json=[{
                "id": 91, "name": "Portal", "description": "Una aventura",
                "theme": "fantasy", "video_url": "https://video.test/portal",
                "min_players": 2, "max_players": 6, "min_age": 12,
                "duration_minutes": 90, "difficulty": 2, "active": True,
                "cover_image": "private-cover.png", "new_internal_column": "secret",
            }])
        if request.url.path == "/api/bookings/opening-hours":
            return httpx.Response(200, json=[{
                "id": 4, "day_of_week": 1, "open_time": "10:00", "close_time": "21:00",
                "is_open": True, "requires_advance_booking": False,
            }])
        if request.url.path == "/api/bookings/quote":
            return httpx.Response(200, json={
                "date": "2026-10-20", "dayType": "weekday", "isHoliday": False,
                "players": 4, "currency": "COP", "pricePerPerson": 50000, "total": 200000,
            })
        if request.url.path == "/api/bookings/availability":
            return httpx.Response(200, json={
                "date": "2026-10-20", "dayType": "weekday", "isHoliday": False,
                "rates": [], "timezone": "America/Bogota",
                "serverNow": "2026-10-17T12:00:00-05:00", "minAdvanceMinutes": 0,
                "rooms": [{
                    "roomId": "portal", "name": "Portal", "minPlayers": 2,
                    "maxPlayers": 6, "durationMinutes": 90, "difficulty": "medium",
                    "slots": [{"start": "2026-10-20T10:00:00-05:00", "available": True}],
                }],
            })
        raise AssertionError(f"Unexpected endpoint: {request.url.path}")

    async def scenario():
        client, http = make_client(handler)
        try:
            rates = await client.get_rates("weekend")
            rooms = await client.get_rooms()
            hours = await client.get_opening_hours()
            quote = await client.get_quote(date(2026, 10, 20), 4)
            availability = await client.get_availability(date(2026, 10, 20))
        finally:
            await http.aclose()
        return rates, rooms, hours, quote, availability

    rates, rooms, hours, quote, availability = asyncio.run(scenario())

    assert rates[0].price_per_person == 50_000
    assert rooms[0].minimum_age_without_adult == 12
    assert rooms[0].difficulty == "medium"
    assert not hasattr(rooms[0], "id")
    assert not hasattr(rooms[0], "theme")
    assert hours[0].day_of_week == 1
    assert quote.total == 200_000
    assert availability.rooms[0].room_id == "portal"
    assert availability.rooms[0].slots[0].available is True
    assert [request.url.path for request in seen] == [
        "/api/rates", "/api/rooms", "/api/bookings/opening-hours",
        "/api/bookings/quote", "/api/bookings/availability",
    ]
    assert seen[0].url.params["dayType"] == "weekend"
    assert dict(seen[3].url.params) == {"date": "2026-10-20", "attendees": "4"}
    assert dict(seen[4].url.params) == {"date": "2026-10-20"}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"code": "DAY_CLOSED"}, LogicDayClosed),
        ({"error": "OPENING_HOURS_MISSING"}, LogicOpeningHoursMissing),
        ({"error": "invalid date"}, LogicInvalidRequest),
    ],
)
def test_maps_bad_request_codes_without_exposing_raw_backend_message(body, expected):
    def handler(request):
        return httpx.Response(400, json=body)

    async def scenario():
        client, http = make_client(handler)
        try:
            await client.get_availability(date(2026, 10, 20))
        finally:
            await http.aclose()

    with pytest.raises(expected) as error:
        asyncio.run(scenario())
    assert "invalid date" not in str(error.value)
    assert error.value.status_code == 400


def test_distinguishes_conflict_server_error_and_timeout():
    async def check(handler):
        client, http = make_client(handler)
        try:
            await client.get_rooms()
        finally:
            await http.aclose()

    with pytest.raises(LogicConflict):
        asyncio.run(check(lambda request: httpx.Response(409, json={"error": "conflict"})))
    with pytest.raises(LogicApiUnavailable):
        asyncio.run(check(lambda request: httpx.Response(503)))

    def timeout(request):
        raise httpx.ReadTimeout("upstream timed out", request=request)

    with pytest.raises(LogicApiUnavailable, match="timed out"):
        asyncio.run(check(timeout))


def test_validates_arguments_and_rejects_invalid_api_payloads():
    async def invalid_arguments():
        client, http = make_client(lambda request: httpx.Response(200, json=[]))
        try:
            with pytest.raises(ValueError):
                await client.get_quote(date(2026, 10, 20), 0)
            with pytest.raises(ValueError):
                await client.get_rates("holiday")  # type: ignore[arg-type]
        finally:
            await http.aclose()

    asyncio.run(invalid_arguments())

    async def invalid_payload():
        client, http = make_client(lambda request: httpx.Response(200, json={"rooms": []}))
        try:
            await client.get_rooms()
        finally:
            await http.aclose()

    with pytest.raises(LogicApiProtocolError):
        asyncio.run(invalid_payload())

    assert adapt_room({"name": "Test", "difficulty": "internal-value"}).difficulty is None


def test_only_reference_data_is_cached():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/rooms":
            return httpx.Response(200, json=[{"name": "Portal"}])
        if request.url.path == "/api/bookings/opening-hours":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/rates":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/bookings/quote":
            return httpx.Response(200, json={
                "date": "2026-10-20", "dayType": "weekday", "isHoliday": False,
                "players": 2, "currency": "COP", "pricePerPerson": 10, "total": 20,
            })
        if request.url.path == "/api/bookings/availability":
            return httpx.Response(200, json={
                "date": "2026-10-20", "dayType": "weekday", "isHoliday": False,
                "timezone": "America/Bogota", "serverNow": "2026-10-17T12:00:00-05:00",
                "minAdvanceMinutes": 0, "rooms": [],
            })
        raise AssertionError(request.url.path)

    async def scenario():
        client, http = make_client(handler)
        try:
            await client.get_rooms()
            await client.get_rooms()
            await client.get_rates()
            await client.get_rates()
            await client.get_opening_hours()
            await client.get_opening_hours()
            for _ in range(2):
                await client.get_quote(date(2026, 10, 20), 2)
                await client.get_availability(date(2026, 10, 20))
        finally:
            await http.aclose()

    asyncio.run(scenario())
    assert calls.count("/api/rooms") == 1
    assert calls.count("/api/rates") == 1
    assert calls.count("/api/bookings/opening-hours") == 1
    assert calls.count("/api/bookings/quote") == 2
    assert calls.count("/api/bookings/availability") == 2


def test_reference_cache_can_be_disabled():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[])

    async def scenario():
        client, http = make_client(handler, ttl=0)
        try:
            await client.get_rooms()
            await client.get_rooms()
        finally:
            await http.aclose()

    asyncio.run(scenario())
    assert calls == ["/api/rooms", "/api/rooms"]
