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

Android uses Credential Manager for sign-in and AuthorizationClient for scopes and access tokens, iOS the
GoogleSignIn SDK, the web and the desktop window Google Identity Services. The ID token's audience is the web
client ID on every platform, so one server check covers all of them.

Differences from React Native: `get_current_user()` and `has_previous_sign_in()` are coroutines (the bridge is
async). Tokens are never stored on the device by this package; the SDKs keep their own.
"""
from __future__ import annotations

import enum
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Union

from pyxpo.module_api import call, native_view, platform, require_linked

__version__ = "0.1.0a2"

NATIVE = "GoogleSignIn"
Response = Dict[str, Any]
User = Dict[str, Any]


class status_codes:
    """Error codes on `GoogleSignInError.code`."""
    SIGN_IN_CANCELLED = "SIGN_IN_CANCELLED"
    IN_PROGRESS = "IN_PROGRESS"
    PLAY_SERVICES_NOT_AVAILABLE = "PLAY_SERVICES_NOT_AVAILABLE"
    SIGN_IN_REQUIRED = "SIGN_IN_REQUIRED"
    NULL_PRESENTER = "NULL_PRESENTER"
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
_USER_KEYS = ("id", "email", "name", "givenName", "familyName", "photo")
_BASIC = ["openid", "email", "profile"]
_CANCELLED: Response = {"type": "cancelled", "data": None}
_NO_SAVED: Response = {"type": "noSavedCredentialFound", "data": None}
_config: Optional[Dict[str, Any]] = None
_busy = False


def configure(web_client_id: Optional[str] = None, ios_client_id: Optional[str] = None,
              scopes: Optional[List[str]] = None, offline_access: bool = False, hosted_domain: Optional[str] = None,
              force_code_for_refresh_token: bool = False, account_name: Optional[str] = None,
              profile_image_size: int = 120, openid_realm: Optional[str] = None, **camel: Any) -> None:
    """Sets the OAuth client IDs and options. Call once at startup, before any other call.

    `web_client_id`: the OAuth client of type "Web application"; it is the audience of the ID token on every
    platform and the client the web page signs in with. `ios_client_id`: the iOS client (its reversed form is the
    URL scheme the config plugin adds). `scopes`: extra OAuth scopes asked for at sign-in. `offline_access`: also
    return a `serverAuthCode` your backend exchanges for a refresh token. `force_code_for_refresh_token`
    (Android): ask for a code that always yields a refresh token. `hosted_domain`: only accept accounts of one
    Google Workspace domain. `profile_image_size` (iOS): edge in pixels of `user.photo`. `openid_realm` (iOS):
    OpenID 2.0 realm. `account_name`: accepted for React Native compatibility; Credential Manager picks the account
    itself, so it has no effect. camelCase names work too (`webClientId=...`)."""
    global _config
    web_client_id = camel.pop("webClientId", web_client_id)
    ios_client_id = camel.pop("iosClientId", ios_client_id)
    offline_access = camel.pop("offlineAccess", offline_access)
    hosted_domain = camel.pop("hostedDomain", hosted_domain)
    force_code_for_refresh_token = camel.pop("forceCodeForRefreshToken", force_code_for_refresh_token)
    account_name = camel.pop("accountName", account_name)
    profile_image_size = camel.pop("profileImageSize", profile_image_size)
    openid_realm = camel.pop("openIdRealm", openid_realm)
    scopes = camel.pop("scopes", scopes)
    if camel:
        raise TypeError("configure() got unknown options %s" % sorted(camel))
    if not web_client_id or not isinstance(web_client_id, str):
        raise ValueError("configure() needs web_client_id, the OAuth client of type Web application")
    for name, v in (("web_client_id", web_client_id), ("ios_client_id", ios_client_id)):
        if v is not None and not v.endswith(".apps.googleusercontent.com"):
            raise ValueError("%s must end with .apps.googleusercontent.com, got %r" % (name, v))
    if isinstance(scopes, str) or not all(isinstance(s, str) and s for s in scopes or []):
        raise ValueError("scopes must be a list of scope strings")
    if isinstance(profile_image_size, bool) or not isinstance(profile_image_size, int) or profile_image_size <= 0:
        raise ValueError("profile_image_size must be a positive int, got %r" % (profile_image_size,))
    _config = {"webClientId": web_client_id, "iosClientId": ios_client_id or "", "scopes": list(scopes or []),
               "offlineAccess": bool(offline_access), "hostedDomain": hosted_domain or "",
               "forceCodeForRefreshToken": bool(force_code_for_refresh_token), "accountName": account_name or "",
               "profileImageSize": profile_image_size, "openIdRealm": openid_realm or ""}


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
        raise GoogleSignInError(status_codes.NOT_CONFIGURED, "call configure(web_client_id=...) first")
    if platform() == "ios" and not _config["iosClientId"]:
        raise GoogleSignInError(status_codes.NOT_CONFIGURED, "iOS needs configure(ios_client_id=...)")
    return _config


def _user(data: Any, cfg: Optional[Dict[str, Any]]) -> User:
    """Fills every key of a signed-in user, so app code can index without `.get`."""
    data = dict(data or {})
    if not data.get("idToken"):
        raise GoogleSignInError(status_codes.NO_ID_TOKEN, "Google returned no ID token; check web_client_id")
    user = dict(data.get("user") or {})
    for k in _USER_KEYS:
        user.setdefault(k, None)
    data["user"] = user
    data.setdefault("serverAuthCode", None)
    if not data.get("scopes"):
        data["scopes"] = list(dict.fromkeys(_BASIC + (cfg["scopes"] if cfg else [])))
    return data


def _success(res: Any, cfg: Optional[Dict[str, Any]]) -> Response:
    if not isinstance(res, dict) or res.get("type") == "cancelled":
        return dict(_CANCELLED)
    if res.get("type") == "noSavedCredentialFound":
        return dict(_NO_SAVED)
    return {"type": "success", "data": _user(res.get("data"), cfg)}


async def _flow(method: str, *args: Any) -> Optional[Response]:
    """Runs one interactive call at a time; a closed sheet comes back as a cancelled response. A None reply
    (no signed-in user, for addScopes) stays None."""
    global _busy
    cfg = _require_config()
    if _busy:
        raise GoogleSignInError(status_codes.IN_PROGRESS, "a sign-in is already in progress")
    _busy = True
    try:
        res = await _native(method, cfg, *args)
    except GoogleSignInError as e:
        if e.code == status_codes.SIGN_IN_CANCELLED:
            return dict(_CANCELLED)
        raise
    finally:
        _busy = False
    return None if res is None and method == "addScopes" else _success(res, cfg)


async def has_play_services(show_play_services_update_dialog: bool = True, **camel: Any) -> bool:
    """Android: True when Google Play services can sign in, else raises PLAY_SERVICES_NOT_AVAILABLE (and shows
    Google's fix-it dialog when `show_play_services_update_dialog`). iOS and the web: always True."""
    show = camel.pop("showPlayServicesUpdateDialog", show_play_services_update_dialog)
    if camel:
        raise TypeError("has_play_services() got unknown options %s" % sorted(camel))
    if platform() != "android":
        return True
    ok = await _native("hasPlayServices", bool(show))
    if not ok:
        raise GoogleSignInError(status_codes.PLAY_SERVICES_NOT_AVAILABLE, "Google Play services is not available")
    return True


async def sign_in(options: Optional[Dict[str, Any]] = None, *, login_hint: Optional[str] = None,
                  nonce: Optional[str] = None) -> Response:
    """Opens Google's account picker. Returns `{"type": "success", "data": {"idToken", "serverAuthCode", "scopes",
    "user": {"id", "email", "name", "givenName", "familyName", "photo"}}}`, or `{"type": "cancelled", "data": None}`
    when the user closes the picker. Raises `GoogleSignInError` (IN_PROGRESS while another sign-in is open).

    `login_hint` (iOS and the web): preselects this email. `nonce` (Android and the web): put into the ID token's
    `nonce` claim for replay protection; the GoogleSignIn iOS SDK has no nonce. React Native's
    `sign_in({"loginHint": ..., "nonce": ...})` form works too."""
    o = dict(options or {})
    login_hint = o.pop("loginHint", login_hint)
    nonce = o.pop("nonce", nonce)
    if o:
        raise TypeError("sign_in() got unknown options %s" % sorted(o))
    res = await _flow("signIn", {"loginHint": login_hint or "", "nonce": nonce or ""})
    return res if res is not None else dict(_CANCELLED)


async def sign_in_silently() -> Response:
    """Signs the previous user back in without UI, for app start. Returns a success response, or
    `{"type": "noSavedCredentialFound", "data": None}` when nobody signed in before (or they signed out)."""
    res = await _flow("signInSilently")
    return dict(_NO_SAVED) if res is None or res["type"] == "cancelled" else res


async def add_scopes(scopes: Union[List[str], Dict[str, Any]]) -> Optional[Response]:
    """Asks the signed-in user for more OAuth scopes, showing Google's consent screen when needed. Returns the
    updated success response, a cancelled response, or None when nobody is signed in. Takes a list or React
    Native's `{"scopes": [...]}`."""
    if isinstance(scopes, dict):
        scopes = scopes.get("scopes") or []
    if isinstance(scopes, str) or not scopes or not all(isinstance(s, str) and s for s in scopes):
        raise ValueError("add_scopes() needs a non-empty list of scope strings")
    res = await _flow("addScopes", list(scopes))
    return None if res is not None and res["type"] == "noSavedCredentialFound" else res


async def get_tokens() -> Dict[str, Optional[str]]:
    """Returns `{"idToken", "accessToken"}` for the signed-in user, refreshing expired ones. Raises
    SIGN_IN_REQUIRED when nobody is signed in. Call it each time you need a token; do not store tokens."""
    res = await _native("getTokens", _require_config())
    res = dict(res or {})
    return {"idToken": res.get("idToken"), "accessToken": res.get("accessToken")}


async def get_current_user() -> Optional[User]:
    """The signed-in user (`{"idToken", "serverAuthCode", "scopes", "user"}`), or None. On Android the ID token
    is only present after `sign_in()` or `sign_in_silently()` in this app run."""
    res = await _native("getCurrentUser", _config or {})
    if not isinstance(res, dict) or res.get("type") != "success" or not res.get("data"):
        return None
    data = dict(res["data"])
    data.setdefault("idToken", None)
    user = dict(data.get("user") or {})
    for k in _USER_KEYS:
        user.setdefault(k, None)
    data["user"] = user
    data.setdefault("serverAuthCode", None)
    data.setdefault("scopes", [])
    return data


async def has_previous_sign_in() -> bool:
    """True when a user signed in before and has not signed out, so `sign_in_silently()` can work."""
    return bool(await _native("hasPreviousSignIn", _config or {}))


async def clear_cached_access_token(token: str) -> None:
    """Android: drops `token` from Google's cache, so the next `get_tokens()` fetches a new one. Use it after
    your API answered 401. iOS: no-op (the SDK refreshes on its own)."""
    if not token or not isinstance(token, str):
        raise ValueError("clear_cached_access_token() needs the access token string")
    await _native("clearCachedAccessToken", token)


async def revoke_access() -> None:
    """Disconnects the app from the user's Google account (revokes every granted scope) and signs out. Offer it
    as "Disconnect Google" or in account deletion."""
    if _config is None:
        return None
    await _native("revokeAccess", _config)
    return None


async def sign_out() -> None:
    """Forgets the signed-in account, so the next `sign_in()` shows the account picker again."""
    if _config is None:
        return None
    await _native("signOut", _config)
    return None


def is_error_with_code(error: Any) -> bool:
    return isinstance(error, GoogleSignInError)


def is_success_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("type") == "success"


def is_cancelled_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("type") == "cancelled"


def is_no_saved_credential_found_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("type") == "noSavedCredentialFound"


class GoogleSigninButtonSize(enum.IntEnum):
    STANDARD = 0
    WIDE = 1
    ICON = 2
    Standard = 0
    Wide = 1
    Icon = 2


class GoogleSigninButtonColor(enum.IntEnum):
    DARK = 0
    LIGHT = 1
    Dark = 0
    Light = 1


_Button = native_view("PxGoogleSigninButton")


def GoogleSigninButton(size: Any = GoogleSigninButtonSize.STANDARD, color: Any = GoogleSigninButtonColor.LIGHT,
                       disabled: bool = False, on_press: Optional[Callable[[Any], Any]] = None,
                       style: Any = None, **props: Any) -> Any:
    """Google's own branded button. `on_press` gets called on a tap: start `sign_in()` there. Default height 48
    (48x48 for `Size.ICON`); override in `style`. `onPress` works too."""
    if "onPress" in props:
        on_press = props.pop("onPress")
    size = GoogleSigninButtonSize(size)
    wire: Dict[str, Any] = {"size": int(size), "color": int(GoogleSigninButtonColor(color)),
                            "disabled": bool(disabled)}
    if on_press is not None:
        wire["on_press"] = on_press
    box: Dict[str, Any] = {"height": 48, "width": 48} if size == GoogleSigninButtonSize.ICON else {"height": 48}
    if isinstance(style, dict):
        box.update(style)
    return _Button(style=box, **wire, **props)


GoogleSigninButton.Size = GoogleSigninButtonSize  # type: ignore[attr-defined]
GoogleSigninButton.Color = GoogleSigninButtonColor  # type: ignore[attr-defined]

hasPlayServices = has_play_services
signIn = sign_in
signInSilently = sign_in_silently
addScopes = add_scopes
getTokens = get_tokens
getCurrentUser = get_current_user
hasPreviousSignIn = has_previous_sign_in
clearCachedAccessToken = clear_cached_access_token
revokeAccess = revoke_access
signOut = sign_out
isErrorWithCode = is_error_with_code
isSuccessResponse = is_success_response
isCancelledResponse = is_cancelled_response
isNoSavedCredentialFoundResponse = is_no_saved_credential_found_response

# `from pyxpo_google_sign_in import GoogleSignin` then `GoogleSignin.configure(...)`, as in React Native.
GoogleSignin = SimpleNamespace(
    configure=configure, has_play_services=has_play_services, hasPlayServices=has_play_services,
    sign_in=sign_in, signIn=sign_in, sign_in_silently=sign_in_silently, signInSilently=sign_in_silently,
    add_scopes=add_scopes, addScopes=add_scopes, get_tokens=get_tokens, getTokens=get_tokens,
    get_current_user=get_current_user, getCurrentUser=get_current_user,
    has_previous_sign_in=has_previous_sign_in, hasPreviousSignIn=has_previous_sign_in,
    clear_cached_access_token=clear_cached_access_token, clearCachedAccessToken=clear_cached_access_token,
    revoke_access=revoke_access, revokeAccess=revoke_access, sign_out=sign_out, signOut=sign_out)

__all__ = [
    "configure", "has_play_services", "sign_in", "sign_in_silently", "add_scopes", "get_tokens",
    "get_current_user", "has_previous_sign_in", "clear_cached_access_token", "revoke_access", "sign_out",
    "status_codes", "statusCodes", "GoogleSignInError", "GoogleSignin", "GoogleSigninButton",
    "GoogleSigninButtonSize", "GoogleSigninButtonColor", "is_error_with_code", "is_success_response",
    "is_cancelled_response", "is_no_saved_credential_found_response", "hasPlayServices", "signIn",
    "signInSilently", "addScopes", "getTokens", "getCurrentUser", "hasPreviousSignIn", "clearCachedAccessToken",
    "revokeAccess", "signOut", "isErrorWithCode", "isSuccessResponse", "isCancelledResponse",
    "isNoSavedCredentialFoundResponse",
]
