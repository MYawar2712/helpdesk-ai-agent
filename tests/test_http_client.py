import pytest
import responses

from clients.http_client import (
    APIResponseValidationError,
    HTTPClient,
    ResourceNotFoundError,
)

POST_URL = "https://jsonplaceholder.typicode.com/posts/1"
USER_URL = "https://jsonplaceholder.typicode.com/users/1"


@responses.activate
def test_fetch_post_returns_validated_pydantic_model() -> None:
    responses.get(
        POST_URL,
        json={"userId": 1, "id": 1, "title": "Hello", "body": "World"},
        status=200,
    )

    post = HTTPClient().fetch_post(1)

    assert post.user_id == 1
    assert post.title == "Hello"
    assert post.model_dump() == {
        "user_id": 1,
        "id": 1,
        "title": "Hello",
        "body": "World",
    }


@responses.activate
def test_fetch_user_validates_nested_payload() -> None:
    responses.get(
        USER_URL,
        json={
            "id": 1,
            "name": "Leanne Graham",
            "username": "Bret",
            "email": "leanne@example.com",
            "address": {
                "street": "Kulas Light",
                "suite": "Apt. 556",
                "city": "Gwenborough",
                "zipcode": "92998-3874",
            },
            "phone": "1-770-736-8031 x56442",
            "website": "hildegard.org",
            "company": {
                "name": "Romaguera-Crona",
                "catch_phrase": "Multi-layered client-server neural-net",
                "bs": "harness real-time e-markets",
            },
        },
        status=200,
    )

    user = HTTPClient().fetch_user(1)

    assert user.address.city == "Gwenborough"
    assert user.company.name == "Romaguera-Crona"


@responses.activate
def test_fetch_post_rejects_malformed_payload() -> None:
    responses.get(POST_URL, json={"userId": "wrong"}, status=200)

    with pytest.raises(APIResponseValidationError):
        HTTPClient().fetch_post(1)


@responses.activate
def test_fetch_post_rejects_malformed_json() -> None:
    responses.get(POST_URL, body="not-json", status=200)

    with pytest.raises(APIResponseValidationError, match="malformed JSON"):
        HTTPClient().fetch_post(1)


@responses.activate
def test_fetch_post_raises_not_found_without_retry() -> None:
    responses.get(POST_URL, status=404)

    with pytest.raises(ResourceNotFoundError):
        HTTPClient().fetch_post(1)

    assert len(responses.calls) == 1


@responses.activate
def test_fetch_post_retries_server_errors_then_succeeds() -> None:
    responses.get(POST_URL, status=500)
    responses.get(
        POST_URL,
        json={"userId": 1, "id": 1, "title": "Recovered", "body": "OK"},
        status=200,
    )

    post = HTTPClient().fetch_post(1)

    assert post.title == "Recovered"
    assert len(responses.calls) == 2


@pytest.mark.parametrize("method", ["fetch_post", "fetch_user"])
def test_fetch_methods_reject_invalid_ids(method: str) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        getattr(HTTPClient(), method)(0)


def test_client_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="base_url"):
        HTTPClient(base_url="")
    with pytest.raises(ValueError, match="timeout"):
        HTTPClient(timeout_seconds=0)
    with pytest.raises(ValueError, match="attempts"):
        HTTPClient(max_attempts=0)
