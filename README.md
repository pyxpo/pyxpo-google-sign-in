# pyxpo-google-sign-in

[![CI](https://github.com/pyxpo/pyxpo-google-sign-in/actions/workflows/ci.yml/badge.svg)](https://github.com/pyxpo/pyxpo-google-sign-in/actions/workflows/ci.yml) [![PyPI](https://img.shields.io/pypi/v/pyxpo-google-sign-in)](https://pypi.org/project/pyxpo-google-sign-in/) [![Python](https://img.shields.io/pypi/pyversions/pyxpo-google-sign-in)](https://pypi.org/project/pyxpo-google-sign-in/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Sign in with Google for [pyxpo](https://github.com/pyxpo/pyxpo) apps written in Python. The API follows
[@react-native-google-signin/google-signin](https://react-native-google-signin.github.io/docs/). Android uses
Credential Manager, iOS the GoogleSignIn SDK, and the web and the desktop window Google Identity Services. You get
an OpenID Connect **ID token** to verify on your server.

```python
import pyxpo_google_sign_in as GoogleSignin

GoogleSignin.configure(web_client_id="1234-web.apps.googleusercontent.com",
                       ios_client_id="1234-ios.apps.googleusercontent.com")
res = await GoogleSignin.sign_in()
if res["type"] == "success":
    await api.post("/auth/google", {"idToken": res["data"]["idToken"]})
```

## Features

- **One ID token for every platform.** Its audience is your web client ID, so one server check covers Android,
  iOS and the web.
- **Native account pickers:** the Credential Manager bottom sheet on Android, Google's sheet on iOS.
- **Clear outcomes:** `{"type": "success"}`, `{"type": "cancelled"}` or `{"type": "noSavedCredentialFound"}`, and
  `GoogleSignInError.code` for the rest.
- **Silent sign-in at app start** with `sign_in_silently()`, no UI when the user signed in before.
- **More scopes later:** `add_scopes()` shows Google's consent screen only for what is new; `get_tokens()` gives
  a fresh access token for Google APIs (Drive, Calendar, ...).
- **Backend access:** `offline_access=True` returns a `serverAuthCode` on Android and iOS.
- **Google's own button:** `GoogleSigninButton` is the native `SignInButton` / `GIDSignInButton`.
- **Disconnect:** `revoke_access()` removes every grant, for "Disconnect Google" and account deletion.
- **Config plugin** for the iOS URL scheme, so you never edit Info.plist.
- **Works on the web and the desktop** with Google Identity Services, so you can develop without a phone.
- **camelCase too:** `GoogleSignin.signIn()`, `webClientId=...`.

## Contents

| If you are... | Start here |
| --- | --- |
| Setting up | [Install](#install) · [Google Cloud setup](#google-cloud-setup) |
| Signing users in | [Quick start](#quick-start) |
| Exact names | [API reference](#api-reference) · [Errors](#errors) |
| Stuck | [Testing](#testing) · [Troubleshooting](#troubleshooting) |

## Install

```bash
pip install pyxpo-google-sign-in
```

Add the module and its config plugin to your app's `pyproject.toml`:

```toml
[tool.pyxpo]
modules = ["google-sign-in"]
plugins = [["pyxpo_google_sign_in.plugin", { iosClientId = "1234-ios.apps.googleusercontent.com" }]]
```

Then rebuild the native app (`pyxpo run ios`, `pyxpo run android`). The plugin writes `GIDClientID` and the reversed
client ID (`com.googleusercontent.apps.1234-ios`) to `CFBundleURLTypes`. The GoogleSignIn SDK stops the app
without that URL scheme.

| Platform | Engine | Minimum |
| --- | --- | --- |
| Android | Credential Manager + `googleid` 1.1 | API 24 |
| iOS | GoogleSignIn 8 (Swift Package) | iOS 15 |
| Web, desktop window | Google Identity Services | any current browser |

## Google Cloud setup

Make three OAuth clients in one Google Cloud project (APIs & Services > Credentials):

| Client type | What you enter | Used by |
| --- | --- | --- |
| **Web application** | Authorized JavaScript origins: your web app's origins (`http://localhost:3000` in development) | `web_client_id` on every platform; your server checks this audience |
| **iOS** | Bundle ID of the app | `ios_client_id` and the plugin |
| **Android** | Package name and the SHA-1 of each signing certificate (debug and release) | nothing in code: Google matches the app by package and certificate |

Get the debug SHA-1 with `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android`.

Client IDs are not secret, but keep them in config rather than spread through code.

## Quick start

```python
import pyxpo_google_sign_in as GoogleSignin
from pyxpo_google_sign_in import GoogleSignInError, status_codes

GoogleSignin.configure(web_client_id=WEB_CLIENT_ID, ios_client_id=IOS_CLIENT_ID)


async def sign_in_with_google():
    try:
        await GoogleSignin.has_play_services()
        await GoogleSignin.sign_out()          # always show the account picker
        res = await GoogleSignin.sign_in()
    except GoogleSignInError as e:
        if e.code == status_codes.IN_PROGRESS:
            return None
        if e.code == status_codes.PLAY_SERVICES_NOT_AVAILABLE:
            return "Update Google Play services, then try again."
        raise
    if res["type"] == "cancelled":
        return None
    return await api.post("/auth/google", {"idToken": res["data"]["idToken"]})
```

Sign the previous user back in at app start, without UI:

```python
res = await GoogleSignin.sign_in_silently()
if res["type"] == "success":
    user = res["data"]["user"]
else:                                  # "noSavedCredentialFound": show the sign-in screen
    ...
```

Google's branded button:

```python
from pyxpo.module_api import spawn
from pyxpo_google_sign_in import GoogleSigninButton

GoogleSigninButton(size=GoogleSigninButton.Size.WIDE, color=GoogleSigninButton.Color.DARK,
                   on_press=lambda _: spawn(sign_in_with_google()))
```

Call a Google API with more scopes:

```python
DRIVE = "https://www.googleapis.com/auth/drive.readonly"
res = await GoogleSignin.add_scopes([DRIVE])        # consent screen once; None when nobody is signed in
if res and res["type"] == "success":
    tokens = await GoogleSignin.get_tokens()       # {"idToken", "accessToken"}
    files = await fetch("https://www.googleapis.com/drive/v3/files",
                        headers={"Authorization": "Bearer " + tokens["accessToken"]})
```

Verify the token on the server: signature against Google's keys, `iss` is `https://accounts.google.com`, `aud` is
your **web** client ID, `exp` in the future, `email_verified` true.

## API reference

| Name | Returns | Notes |
| --- | --- | --- |
| `configure(web_client_id, ios_client_id=None, scopes=None, offline_access=False, hosted_domain=None, force_code_for_refresh_token=False, profile_image_size=120, openid_realm=None, account_name=None)` | `None` | Call once at startup. Validates the client IDs. |
| `await has_play_services(show_play_services_update_dialog=True)` | `True` | Android only checks; raises `PLAY_SERVICES_NOT_AVAILABLE`. iOS and the web: `True`. |
| `await sign_in(login_hint=None, nonce=None)` | response | `success` or `cancelled`. Also takes `{"loginHint": ..., "nonce": ...}`. |
| `await sign_in_silently()` | response | `success` or `noSavedCredentialFound`. No UI. |
| `await add_scopes(scopes)` | response or `None` | `None` when nobody is signed in. |
| `await get_tokens()` | `{"idToken", "accessToken"}` | Refreshes expired tokens. Raises `SIGN_IN_REQUIRED` when nobody is signed in. |
| `await get_current_user()` | `data` or `None` | The signed-in user, without a network call. |
| `await has_previous_sign_in()` | `bool` | True when `sign_in_silently()` can work. |
| `await clear_cached_access_token(token)` | `None` | Android: drop a token your API rejected. iOS: no-op. |
| `await revoke_access()` | `None` | Removes every grant and signs out. |
| `await sign_out()` | `None` | Clears the remembered account, so the next sign-in shows the picker. |
| `GoogleSigninButton(size, color, disabled=False, on_press=None, style=None)` | view | `Size.STANDARD/WIDE/ICON`, `Color.LIGHT/DARK`. Height 48. |
| `is_success_response`, `is_cancelled_response`, `is_no_saved_credential_found_response` | `bool` | |
| `is_error_with_code(e)` | `bool` | True for `GoogleSignInError`. |
| `GoogleSignin` | namespace | `GoogleSignin.signIn()` and friends, React Native style. |

`data` holds `idToken`, `serverAuthCode` (with `offline_access`, else `None`), `scopes` and `user`: `id`,
`email`, `name`, `givenName`, `familyName`, `photo`. `id` is Google's stable account ID (the token's `sub`).

### Platform notes

| | Android | iOS | Web and desktop |
| --- | --- | --- | --- |
| Sign-in UI | Credential Manager sheet | GoogleSignIn sheet | Google button in a small sheet |
| `nonce` | yes | no (SDK has none) | yes |
| `login_hint` | no | yes | yes |
| `serverAuthCode` | yes | yes | no |
| `add_scopes`, `get_tokens` | AuthorizationClient | GoogleSignIn | GIS token client |

Differences from React Native: `get_current_user()` and `has_previous_sign_in()` are coroutines. This package
never writes tokens to disk; on Android the ID token lives in memory for the app run.

## Errors

`GoogleSignInError.code` is one of `status_codes`:

| Code | When | What to do |
| --- | --- | --- |
| `IN_PROGRESS` | `sign_in()` while another is open | Ignore the second tap. |
| `PLAY_SERVICES_NOT_AVAILABLE` | Android without current Google Play services | Ask the user to update it. |
| `SIGN_IN_REQUIRED` | no Google account on the device, or `get_tokens()` with nobody signed in | Show the sign-in screen. |
| `NULL_PRESENTER` | iOS has no view controller to show the sheet from | Call after the first screen is on screen. |
| `NOT_CONFIGURED` | no `configure()`, or no `ios_client_id` on iOS | Call `configure` at startup. |
| `NO_ID_TOKEN` | Google returned no ID token | Check `web_client_id` is the **Web application** client. |
| `FAILED` | anything else; the message comes from the SDK | Show a generic error, log the message. |

A cancelled picker or consent screen is not an error: `sign_in()` and `add_scopes()` return
`{"type": "cancelled"}`.

## Testing

Use `FakeBridge` from pyxpo to run your sign-in logic on the desktop:

```python
from pyxpo.module_testing import FakeBridge
import pyxpo_google_sign_in as G

def test_sign_in():
    G.configure(web_client_id="1-w.apps.googleusercontent.com")
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg, opts: {"type": "success", "data": {"idToken": "t", "user": {}}})
        assert asyncio.run(G.sign_in())["data"]["idToken"] == "t"
```

## Troubleshooting

- **Android: `FAILED: ... 10` or "developer console is not set up correctly".** The Android OAuth client is missing
  the SHA-1 of the certificate that signed this build. Add the debug and the release SHA-1.
- **iOS: the app stops at sign-in.** The URL scheme is missing. Add the plugin with `iosClientId` and rebuild.
- **Web: "The given origin is not allowed".** Add the page origin to the web client's Authorized JavaScript origins.
- **Android: the consent screen never shows for `add_scopes()`.** Enable the API (Drive, Calendar, ...) in the
  same Google Cloud project as the OAuth clients.
- **`NO_ID_TOKEN`.** `web_client_id` is an Android or iOS client. Use the Web application client.

## License

MIT
