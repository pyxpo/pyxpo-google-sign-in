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
- **Clear outcomes:** `{"type": "success"}` or `{"type": "cancelled"}`, and `GoogleSignInError.code` for the rest.
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

Verify the token on the server: signature against Google's keys, `iss` is `https://accounts.google.com`, `aud` is
your **web** client ID, `exp` in the future, `email_verified` true.

## API reference

| Name | Returns | Notes |
| --- | --- | --- |
| `configure(web_client_id, ios_client_id=None, scopes=None, offline_access=False, hosted_domain=None)` | `None` | Call once at startup. Validates the client IDs. |
| `await has_play_services(show_play_services_update_dialog=True)` | `True` | Android only checks; raises `PLAY_SERVICES_NOT_AVAILABLE`. iOS and the web: `True`. |
| `await sign_in()` | response | `{"type": "success", "data": {...}}` or `{"type": "cancelled", "data": None}`. |
| `await sign_out()` | `None` | Clears the remembered account, so the next sign-in shows the picker. |
| `is_success_response(r)`, `is_cancelled_response(r)` | `bool` | |
| `is_error_with_code(e)` | `bool` | True for `GoogleSignInError`. |
| `GoogleSignin` | namespace | `GoogleSignin.signIn()` and friends, React Native style. |

`data` holds `idToken`, `serverAuthCode` (iOS with `offline_access`, else `None`), `scopes` and `user`:
`id`, `email`, `name`, `givenName`, `familyName`, `photo`. On Android `id` is the account email.

## Errors

`GoogleSignInError.code` is one of `status_codes`:

| Code | When | What to do |
| --- | --- | --- |
| `IN_PROGRESS` | `sign_in()` while another is open | Ignore the second tap. |
| `PLAY_SERVICES_NOT_AVAILABLE` | Android without current Google Play services | Ask the user to update it. |
| `SIGN_IN_REQUIRED` | Android has no Google account to offer | Ask the user to add one in Settings. |
| `NOT_CONFIGURED` | no `configure()`, or no `ios_client_id` on iOS | Call `configure` at startup. |
| `NO_ID_TOKEN` | Google returned no ID token | Check `web_client_id` is the **Web application** client. |
| `FAILED` | anything else; the message comes from the SDK | Show a generic error, log the message. |

A cancelled picker is not an error: `sign_in()` returns `{"type": "cancelled"}`.

## Testing

Use `FakeBridge` from pyxpo to run your sign-in logic on the desktop:

```python
from pyxpo.module_testing import FakeBridge
import pyxpo_google_sign_in as G

def test_sign_in():
    G.configure(web_client_id="1-w.apps.googleusercontent.com")
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg: {"type": "success", "data": {"idToken": "t", "user": {}}})
        assert asyncio.run(G.sign_in())["data"]["idToken"] == "t"
```

## Troubleshooting

- **Android: `FAILED: ... 10` or "developer console is not set up correctly".** The Android OAuth client is missing
  the SHA-1 of the certificate that signed this build. Add the debug and the release SHA-1.
- **iOS: the app stops at sign-in.** The URL scheme is missing. Add the plugin with `iosClientId` and rebuild.
- **Web: "The given origin is not allowed".** Add the page origin to the web client's Authorized JavaScript origins.
- **`NO_ID_TOKEN`.** `web_client_id` is an Android or iOS client. Use the Web application client.

## License

MIT
