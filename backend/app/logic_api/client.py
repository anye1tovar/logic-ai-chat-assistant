from datetime import date, datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.logic_api.adapter import adapt_rooms
from app.logic_api.cache import ReferenceDataCache
from app.logic_api.errors import (
    LogicApiError,
    LogicApiProtocolError,
    LogicApiUnavailable,
    LogicConflict,
    LogicDayClosed,
    LogicInvalidRequest,
    LogicNotFound,
    LogicOpeningHoursMissing,
)
from app.logic_api.models import Availability, DayType, OpeningHours, Quote, Rate, Room

ModelT = TypeVar("ModelT", bound=BaseModel)


class LogicApiClient:
    """Async typed client for the documented assistant-facing Logic endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
        cache_ttl_seconds: int | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        resolved_base_url = base_url or settings.logic_api_base_url
        if not resolved_base_url:
            raise ValueError("LOGIC_API_BASE_URL must be configured.")

        self._base_url = resolved_base_url.rstrip("/")
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.logic_api_timeout_seconds
        )
        ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.logic_reference_cache_ttl_seconds
        )
        self._cache = ReferenceDataCache(ttl_seconds=ttl)
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> "LogicApiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def get_rates(self, day_type: DayType | None = None) -> list[Rate]:
        if day_type not in (None, "weekday", "weekend"):
            raise ValueError("day_type must be 'weekday' or 'weekend'.")
        key = ("rates", day_type)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        params = {"dayType": day_type} if day_type else None
        payload = await self._get_json("/api/rates", params=params)
        rates = self._parse_list(payload, Rate, "rates")
        self._cache.set(key, tuple(rates))
        return rates

    async def get_quote(self, requested_date: date, attendees: int) -> Quote:
        if not isinstance(requested_date, date) or isinstance(requested_date, datetime):
            raise ValueError("requested_date must be a date.")
        if isinstance(attendees, bool) or not isinstance(attendees, int) or attendees < 1:
            raise ValueError("attendees must be at least 1.")
        payload = await self._get_json(
            "/api/bookings/quote",
            params={"date": requested_date.isoformat(), "attendees": attendees},
        )
        return self._parse_model(payload, Quote, "quote")

    async def get_rooms(self) -> list[Room]:
        key = ("rooms",)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        rooms = adapt_rooms(await self._get_json("/api/rooms"))
        self._cache.set(key, tuple(rooms))
        return rooms

    async def get_opening_hours(self) -> list[OpeningHours]:
        key = ("opening_hours",)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        payload = await self._get_json("/api/bookings/opening-hours")
        hours = self._parse_list(payload, OpeningHours, "opening hours")
        self._cache.set(key, tuple(hours))
        return hours

    async def get_availability(self, requested_date: date) -> Availability:
        if not isinstance(requested_date, date) or isinstance(requested_date, datetime):
            raise ValueError("requested_date must be a date.")
        payload = await self._get_json(
            "/api/bookings/availability", params={"date": requested_date.isoformat()}
        )
        # Availability is a live snapshot: it is deliberately never cached.
        return self._parse_model(payload, Availability, "availability")

    async def _get_json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        client = self._get_http_client()
        try:
            response = await client.get(
                f"{self._base_url}{path}", params=params, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise LogicApiUnavailable("The Logic API request timed out.") from exc
        except httpx.RequestError as exc:
            raise LogicApiUnavailable("The Logic API could not be reached.") from exc

        if response.is_error:
            self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise LogicApiProtocolError(
                "The Logic API returned a non-JSON response.", status_code=response.status_code
            ) from exc

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
        return self._http_client

    @staticmethod
    def _parse_list(payload: Any, model: type[ModelT], label: str) -> list[ModelT]:
        if not isinstance(payload, list):
            raise LogicApiProtocolError(f"The Logic API {label} response must be an array.")
        return [LogicApiClient._parse_model(item, model, label) for item in payload]

    @staticmethod
    def _parse_model(payload: Any, model: type[ModelT], label: str) -> ModelT:
        try:
            return model.model_validate(payload)
        except (ValidationError, TypeError) as exc:
            raise LogicApiProtocolError(
                f"The Logic API {label} response did not match the supported contract."
            ) from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        error_code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error_code = str(body.get("code") or body.get("error") or "").upper()
        except ValueError:
            pass

        status = response.status_code
        if status == 400 and error_code == "DAY_CLOSED":
            raise LogicDayClosed("The requested date is closed.", status_code=status)
        if status == 400 and error_code == "OPENING_HOURS_MISSING":
            raise LogicOpeningHoursMissing(
                "Opening hours are not configured for the requested date.",
                status_code=status,
            )
        if status == 400:
            raise LogicInvalidRequest("The Logic API rejected the request.", status_code=status)
        if status == 404:
            raise LogicNotFound("The requested Logic API resource was not found.", status_code=status)
        if status == 409:
            raise LogicConflict("The Logic API reported a conflict.", status_code=status)
        if status >= 500:
            raise LogicApiUnavailable(
                "The Logic API returned a server error.", status_code=status
            )
        if status in (401, 403):
            raise LogicApiError(
                "The Logic API rejected the request due to access restrictions.",
                status_code=status,
            )
        raise LogicApiError("The Logic API request failed.", status_code=status)


def create_logic_api_client(settings: Settings | None = None) -> LogicApiClient:
    """Build the shared client from the typed application settings."""
    resolved_settings = settings or get_settings()
    if not resolved_settings.logic_api_base_url:
        raise ValueError("LOGIC_API_BASE_URL must be configured.")
    return LogicApiClient(
        resolved_settings.logic_api_base_url,
        timeout_seconds=resolved_settings.logic_api_timeout_seconds,
        cache_ttl_seconds=resolved_settings.logic_reference_cache_ttl_seconds,
    )
