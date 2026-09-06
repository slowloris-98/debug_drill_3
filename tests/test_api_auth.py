"""Public API authentication.

The published contract (see `api/authentication.py`): a missing, unknown or
revoked key is answered with 401 and a `WWW-Authenticate` header. Client SDKs
refresh credentials on 401 and page a human on 403.
"""

import pytest

from tests.conftest import HELIO_KEY, HELIO_REVOKED_KEY, UNKNOWN_KEY, auth

pytestmark = pytest.mark.django_db

USAGE = "/api/v1/usage/"


def test_an_unknown_key_is_rejected_as_unauthorized(api_client):
    response = api_client.get(USAGE, **auth(UNKNOWN_KEY))
    assert response.status_code == 401, f"got {response.status_code}"


def test_a_revoked_key_is_rejected_as_unauthorized(api_client):
    response = api_client.get(USAGE, **auth(HELIO_REVOKED_KEY))
    assert response.status_code == 401, f"got {response.status_code}"


def test_a_rejection_tells_the_caller_which_scheme_to_use(api_client):
    response = api_client.get(USAGE, **auth(HELIO_REVOKED_KEY))
    assert "WWW-Authenticate" in response.headers, (
        f"no challenge header; response carried {sorted(response.headers)}"
    )
    assert response.headers["WWW-Authenticate"].startswith("Api-Key")


def test_a_revoked_key_is_not_rescued_by_a_signed_in_browser_session(api_client):
    # Rina is signed in to the dashboard in the same browser. That must not
    # make a revoked API key start working again.
    assert api_client.login(username="rokafor", password="meterly")
    response = api_client.get(USAGE, **auth(HELIO_REVOKED_KEY))
    assert response.status_code == 401, (
        f"a revoked key returned {response.status_code} because a session was present"
    )


def test_a_valid_key_still_authenticates(api_client):
    response = api_client.get(USAGE, **auth(HELIO_KEY))
    assert response.status_code == 200


def test_a_key_only_ever_sees_its_own_organizations_usage(api_client):
    response = api_client.get(USAGE, **auth(HELIO_KEY))
    ids = [row["external_id"] for row in response.json()["results"]]
    assert ids and all(external_id.startswith("evt_helio_") for external_id in ids)
