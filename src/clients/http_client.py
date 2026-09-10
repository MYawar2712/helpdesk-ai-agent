"""Typed HTTP client for the JSONPlaceholder demonstration API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class APIClientError(RuntimeError):
    """Base error for failures returned by the external API."""


class ResourceNotFoundError(APIClientError):
    """Raised when the requested API resource does not exist."""


class APIResponseValidationError(APIClientError):
    """Raised when an API response does not match its expected schema."""


class _TransientAPIError(APIClientError):
    """Internal signal for retryable HTTP server failures."""


class ExternalPost(BaseModel):
    """Validated JSONPlaceholder post payload."""

    model_config = ConfigDict(strict=True, extra="forbid")

    user_id: int = Field(validation_alias="userId")
    id: int
    title: str
    body: str


class ExternalAddress(BaseModel):
    """Validated JSONPlaceholder address payload."""

    model_config = ConfigDict(strict=True, extra="forbid")

    street: str
    suite: str
    city: str
    zipcode: str


class ExternalCompany(BaseModel):
    """Validated JSONPlaceholder company payload."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    catch_phrase: str
    bs: str


class ExternalUser(BaseModel):
    """Validated JSONPlaceholder user payload."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    name: str
    username: str
    email: str
    address: ExternalAddress
    phone: str
    website: str
    company: ExternalCompany


@dataclass(slots=True)
class HTTPClient:
    """Small resilient client for JSONPlaceholder resources."""

    base_url: str = "https://jsonplaceholder.typicode.com"
    timeout_seconds: float = 5.0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def fetch_post(self, post_id: int) -> ExternalPost:
        """Fetch and validate one external post."""

        payload = self._get_json(f"/posts/{self._validate_id(post_id, 'post_id')}")
        return self._validate_payload(ExternalPost, payload)

    def fetch_user(self, user_id: int) -> ExternalUser:
        """Fetch and validate one external user."""

        payload = self._get_json(f"/users/{self._validate_id(user_id, 'user_id')}")
        return self._validate_payload(ExternalUser, payload)

    @staticmethod
    def _validate_id(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{field_name} must be a positive integer")
        return value

    @staticmethod
    def _validate_payload(model: type[BaseModel], payload: Any) -> Any:
        try:
            return model.model_validate(payload)
        except ValidationError as error:
            raise APIResponseValidationError(
                f"Response did not match {model.__name__}: {error}"
            ) from error

    def _request(self, path: str) -> requests.Response:
        retrying = Retrying(
            retry=retry_if_exception_type(
                (requests.RequestException, _TransientAPIError)
            ),
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.1, min=0.1, max=1),
            reraise=True,
        )
        return retrying(self._request_once, path)

    def _request_once(self, path: str) -> requests.Response:
        response = requests.get(
            f"{self.base_url.rstrip('/')}{path}", timeout=self.timeout_seconds
        )
        if 500 <= response.status_code <= 599:
            raise _TransientAPIError(
                f"Transient API failure: HTTP {response.status_code}"
            )
        if response.status_code == 404:
            raise ResourceNotFoundError(f"Resource not found: {path}")
        if 400 <= response.status_code <= 499:
            raise APIClientError(f"API request failed: HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def _get_json(self, path: str) -> Any:
        try:
            return self._request(path).json()
        except requests.exceptions.JSONDecodeError as error:
            raise APIResponseValidationError("API returned malformed JSON") from error
