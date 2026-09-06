"""Authentication for the public API.

Contract, as published in our API docs:

    Every request must carry `Authorization: Api-Key <key>`.

    A request whose key is missing, unknown, or revoked is answered with
    **401 Unauthorized** and a `WWW-Authenticate` header telling the caller what
    scheme to use. Client SDKs are expected to treat 401 as "refresh your
    credentials and retry" and 403 as "this key is fine but you may not do that."
    Getting that distinction wrong turns a self-healing failure into a page.
"""

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from core.models import ApiKey

KEYWORD = "Api-Key"


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith(f"{KEYWORD} "):
            raise AuthenticationFailed("Missing key")

        raw_key = header[len(KEYWORD) + 1 :].strip()

        try:
            api_key = ApiKey.objects.select_related("organization").get(key=raw_key)
        except ApiKey.DoesNotExist:
            raise AuthenticationFailed("Invalid key")

        if api_key.revoked_at is not None:
            raise AuthenticationFailed("Key revoked")

        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
        return (api_key.organization.owner, api_key)

    def authenticate_header(self, request):
        return "Api-Key"