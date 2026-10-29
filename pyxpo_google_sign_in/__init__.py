"""Sign in with Google: the @react-native-google-signin/google-signin API.

    import pyxpo_google_sign_in as GoogleSignin
    from pyxpo_google_sign_in import status_codes, is_error_with_code

    GoogleSignin.configure(web_client_id="1234-abc.apps.googleusercontent.com",
                           ios_client_id="1234-def.apps.googleusercontent.com")
    try:
        await GoogleSignin.has_play_services()
        res = await GoogleSignin.sign_in()
        if res["type"] == "success":
            id_token = res["data"]["idToken"]     # send to your server, verify there
    except Exception as e:
        if is_error_with_code(e) and e.code == status_codes.IN_PROGRESS:
            ...

Android uses Credential Manager ("Sign in with Google" button flow), iOS the GoogleSignIn SDK, the web and the
desktop window Google Identity Services. The ID token's audience is the web client ID on every platform, so one
server check covers all of them.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pyxpo.module_api import call, platform, require_linked

__version__ = "0.1.0a1"

NATIVE = "GoogleSignIn"
Response = Dict[str, Any]


class status_codes:
    """Error codes on `GoogleSignInError.code`."""
    SIGN_IN_CANCELLED = "SIGN_IN_CANCELLED"
    IN_PROGRESS = "IN_PROGRESS"
    PLAY_SERVICES_NOT_AVAILABLE = "PLAY_SERVICES_NOT_AVAILABLE"
    SIGN_IN_REQUIRED = "SIGN_IN_REQUIRED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NO_ID_TOKEN = "NO_ID_TOKEN"
    FAILED = "FAILED"


statusCodes = status_codes


class GoogleSignInError(Exception):
    """A failed call. `code` is one of `status_codes`; the message comes from the platform SDK."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


_CODE_RE = re.compile(r"^([A-Z][A-Z_]+):\s*(.*)$", re.S)
_config: Optional[Dict[str, Any]] = None
_busy = False


def configure(web_client_id: Optional[str] = None, ios_client_id: Optional[str] = None,
              scopes: Optional[List[str]] = None, offline_access: bool = False, hosted_domain: Optional[str] = None,
              **camel: Any) -> None:
    """Sets the OAuth client IDs. Call once at startup, before `sign_in()`.

    `web_client_id`: the OAuth client of type "Web application"; it is the audience of the ID token on every
    platform and the client the web page signs in with. `ios_client_id`: the iOS client (its reversed form is
    the URL scheme the config plugin adds). `scopes`: extra OAuth scopes (iOS and the web). `offline_access`:
    also ask for a server auth code. `hosted_domain`: limit accounts to one Google Workspace domain.
    camelCase names work too (`webClientId=...`)."""
    global _config
    web_client_id = camel.pop("webClientId", web_client_id)
    ios_client_id = camel.pop("iosClientId", ios_client_id)
    offline_access = camel.pop("offlineAccess", offline_access)
    hosted_domain = camel.pop("hostedDomain", hosted_domain)
    scopes = camel.pop("scopes", scopes)
    if camel:
        raise TypeError("configure() got unknown options %s" % sorted(camel))
    if not web_client_id or not isinstance(web_client_id, str):
        raise ValueError("configure() needs web_client_id, the OAuth client of type Web application")
    for name, v in (("web_client_id", web_client_id), ("ios_client_id", ios_client_id)):
        if v is not None and not v.endswith(".apps.googleusercontent.com"):
            raise ValueError("%s must end with .apps.googleusercontent.com, got %r" % (name, v))
    _config = {"webClientId": web_client_id, "iosClientId": ios_client_id or "", "scopes": list(scopes or []),
               "offlineAccess": bool(offline_access), "hostedDomain": hosted_domain or ""}


def _error(e: BaseException) -> GoogleSignInError:
    if isinstance(e, GoogleSignInError):
        return e
    m = _CODE_RE.match(str(e))
    if m:
        return GoogleSignInError(m.group(1), m.group(2))
    return GoogleSignInError(status_codes.FAILED, str(e))


async def _native(method: str, *args: Any) -> Any:
    require_linked(NATIVE, "google-sign-in", package="pyxpo-google-sign-in")
    try:
        return await call(NATIVE, method, *args, reply=True)
    except Exception as e:  # native replies "CODE: message"
        raise _error(e) from None


def _require_config() -> Dict[str, Any]:
    if _config is None:
        raise GoogleSignInError(status_codes.NOT_CONFIGURED, "call configure(web_client_id=...) before sign_in()")
    if platform() == "ios" and not _config["iosClientId"]:
        raise GoogleSignInError(status_codes.NOT_CONFIGURED, "iOS needs configure(ios_client_id=...)")
    return _config


async def has_play_services(show_play_services_update_dialog: bool = True, **camel: Any) -> bool:
    """Android: True when Google Play services can sign in, else raises PLAY_SERVICES_NOT_AVAILABLE (and shows
    Google's fix-it dialog when `show_play_services_update_dialog`). iOS and the web: always True."""
    show = camel.pop("showPlayServicesUpdateDialog", show_play_services_update_dialog)
    if platform() != "android":
        return True
    ok = await _native("hasPlayServices", bool(show))
    if not ok:
        raise GoogleSignInError(status_codes.PLAY_SERVICES_NOT_AVAILABLE, "Google Play services is not available")
    return True


async def sign_in() -> Response:
    """Opens Google's account picker. Returns `{"type": "success", "data": {"idToken", "serverAuthCode", "scopes",
    "user": {"id", "email", "name", "givenName", "familyName", "photo"}}}`, or `{"type": "cancelled", "data": None}`
    when the user closes the picker. Raises `GoogleSignInError` (IN_PROGRESS while another sign-in is open)."""
    global _busy
    cfg = _require_config()
    if _busy:
        raise GoogleSignInError(status_codes.IN_PROGRESS, "a sign-in is already in progress")
    _busy = True
    try:
        res = await _native("signIn", cfg)
    except GoogleSignInError as e:
        if e.code == status_codes.SIGN_IN_CANCELLED:
            return {"type": "cancelled", "data": None}
        raise
    finally:
        _busy = False
    if not isinstance(res, dict) or res.get("type") == "cancelled":
        return {"type": "cancelled", "data": None}
    data = dict(res.get("data") or {})
    if not data.get("idToken"):
        raise GoogleSignInError(status_codes.NO_ID_TOKEN, "Google returned no ID token; check web_client_id")
    user = dict(data.get("user") or {})
    for k in ("id", "email", "name", "givenName", "familyName", "photo"):
        user.setdefault(k, None)
    data["user"] = user
    data.setdefault("serverAuthCode", None)
    data.setdefault("scopes", list(cfg["scopes"]))
    return {"type": "success", "data": data}


async def sign_out() -> None:
    """Forgets the signed-in account, so the next `sign_in()` shows the account picker again."""
    if _config is None:
        return None
    await _native("signOut")
    return None


def is_error_with_code(error: Any) -> bool:
    return isinstance(error, GoogleSignInError)


def is_success_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("type") == "success"


def is_cancelled_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("type") == "cancelled"


# `from pyxpo_google_sign_in import GoogleSignin` then `GoogleSignin.configure(...)`, as in React Native.
GoogleSignin = SimpleNamespace(configure=configure, has_play_services=has_play_services,
                               hasPlayServices=has_play_services, sign_in=sign_in, signIn=sign_in,
                               sign_out=sign_out, signOut=sign_out)
hasPlayServices = has_play_services
signIn = sign_in
signOut = sign_out
isErrorWithCode = is_error_with_code
isSuccessResponse = is_success_response
isCancelledResponse = is_cancelled_response

__all__ = ["configure", "has_play_services", "sign_in", "sign_out", "status_codes", "statusCodes",
           "GoogleSignInError", "GoogleSignin", "is_error_with_code", "is_success_response",
           "is_cancelled_response", "hasPlayServices", "signIn", "signOut", "isErrorWithCode", "isSuccessResponse",
           "isCancelledResponse"]
