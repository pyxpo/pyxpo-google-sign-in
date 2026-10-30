"""pyxpo-google-sign-in: configure, the sign-in responses, error codes and the iOS config plugin."""
import asyncio

import pytest

from pyxpo.app_config import ConfigError
from pyxpo.config_plugins import Mods, PluginConfig
from pyxpo.module_testing import FakeBridge

import pyxpo_google_sign_in as G
from pyxpo_google_sign_in import GoogleSignInError, status_codes
from pyxpo_google_sign_in.plugin import plugin, url_scheme

WEB = "1234-web.apps.googleusercontent.com"
IOS = "1234-ios.apps.googleusercontent.com"
TOKEN = "eyJ.a.b"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh():
    G._config, G._busy = None, False
    yield
    G._config, G._busy = None, False


def test_configure_validates():
    with pytest.raises(ValueError):
        G.configure()
    with pytest.raises(ValueError):
        G.configure(web_client_id="not-a-client")
    with pytest.raises(TypeError):
        G.configure(web_client_id=WEB, bogus=1)
    G.configure(webClientId=WEB, iosClientId=IOS, offlineAccess=True)
    assert G._config["webClientId"] == WEB and G._config["iosClientId"] == IOS and G._config["offlineAccess"]


def test_sign_in_needs_configure():
    with FakeBridge("android"):
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.NOT_CONFIGURED
        G.configure(web_client_id=WEB)
    with FakeBridge("ios"):
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.NOT_CONFIGURED


def test_android_success_fills_user():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg, o: {"type": "success", "data": {
            "idToken": TOKEN, "user": {"email": "a@b.co", "name": "A B"}}})
        res = run(G.GoogleSignin.signIn())
        assert G.is_success_response(res)
        assert res["data"]["idToken"] == TOKEN
        assert res["data"]["user"]["email"] == "a@b.co" and res["data"]["user"]["photo"] is None
        assert fb.calls[0][2][0]["webClientId"] == WEB


def test_cancel_and_no_token():
    G.configure(web_client_id=WEB, ios_client_id=IOS)
    with FakeBridge("ios") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg, o: {"type": "cancelled"})
        assert G.is_cancelled_response(run(G.sign_in()))

        def cancelled(cfg, o):
            raise RuntimeError("SIGN_IN_CANCELLED: closed")
        fb.on("GoogleSignIn", "signIn", cancelled)
        assert run(G.sign_in()) == {"type": "cancelled", "data": None}
        fb.on("GoogleSignIn", "signIn", lambda cfg, o: {"type": "success", "data": {"user": {}}})
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.NO_ID_TOKEN


def test_native_error_codes():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        def fail(cfg, o):
            raise RuntimeError("SIGN_IN_REQUIRED: no Google account")
        fb.on("GoogleSignIn", "signIn", fail)
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.SIGN_IN_REQUIRED and str(e.value) == "no Google account"
        assert G.is_error_with_code(e.value)

        def plain(cfg, o):
            raise RuntimeError("boom")
        fb.on("GoogleSignIn", "signIn", plain)
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.FAILED
        assert G._busy is False


def test_in_progress():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg, o: {"type": "cancelled"})
        G._busy = True
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.IN_PROGRESS
        assert fb.calls == []


def test_play_services_and_sign_out():
    with FakeBridge("ios"):
        assert run(G.has_play_services()) is True
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "hasPlayServices", lambda show: False)
        with pytest.raises(GoogleSignInError) as e:
            run(G.hasPlayServices(showPlayServicesUpdateDialog=False))
        assert e.value.code == status_codes.PLAY_SERVICES_NOT_AVAILABLE
        assert fb.calls[-1][2] == (False,)
        fb.on("GoogleSignIn", "hasPlayServices", lambda show: True)
        assert run(G.has_play_services()) is True
        run(G.sign_out())  # not configured: no native call
        assert [c[1] for c in fb.calls].count("signOut") == 0
        G.configure(web_client_id=WEB)
        fb.on("GoogleSignIn", "signOut", lambda cfg: None)
        run(G.sign_out())
        assert fb.calls[-1][1] == "signOut"


USER = {"type": "success", "data": {"idToken": TOKEN, "user": {"id": "1", "email": "a@b.co"},
                                   "scopes": ["openid", "email", "profile"]}}


def test_configure_new_options():
    G.configure(web_client_id=WEB, forceCodeForRefreshToken=True, profileImageSize=200, openIdRealm="r",
                accountName="a@b.co", scopes=["https://www.googleapis.com/auth/drive.readonly"])
    c = G._config
    assert c["forceCodeForRefreshToken"] and c["profileImageSize"] == 200 and c["openIdRealm"] == "r"
    for bad in ({"profile_image_size": 0}, {"profile_image_size": True}, {"scopes": "drive"}):
        with pytest.raises(ValueError):
            G.configure(web_client_id=WEB, **bad)


def test_sign_in_options_reach_native():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg, o: USER)
        run(G.sign_in({"loginHint": "a@b.co", "nonce": "n1"}))
        assert fb.calls[-1][2][1] == {"loginHint": "a@b.co", "nonce": "n1"}
        run(G.sign_in(nonce="n2"))
        assert fb.calls[-1][2][1] == {"loginHint": "", "nonce": "n2"}
        with pytest.raises(TypeError):
            run(G.sign_in({"bogus": 1}))


def test_sign_in_silently():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signInSilently", lambda cfg: {"type": "noSavedCredentialFound"})
        res = run(G.signInSilently())
        assert G.is_no_saved_credential_found_response(res) and res["data"] is None
        fb.on("GoogleSignIn", "signInSilently", lambda cfg: USER)
        res = run(G.sign_in_silently())
        assert G.is_success_response(res) and res["data"]["user"]["photo"] is None


def test_add_scopes():
    G.configure(web_client_id=WEB)
    drive = "https://www.googleapis.com/auth/drive.readonly"
    with FakeBridge("ios") as fb:
        G.configure(web_client_id=WEB, ios_client_id=IOS)
        fb.on("GoogleSignIn", "addScopes", lambda cfg, scopes: None)
        assert run(G.add_scopes([drive])) is None
        granted = {"type": "success", "data": dict(USER["data"], scopes=USER["data"]["scopes"] + [drive])}
        fb.on("GoogleSignIn", "addScopes", lambda cfg, scopes: granted)
        res = run(G.addScopes({"scopes": [drive]}))
        assert drive in res["data"]["scopes"] and fb.calls[-1][2][1] == [drive]

        def closed(cfg, scopes):
            raise RuntimeError("SIGN_IN_CANCELLED: closed")
        fb.on("GoogleSignIn", "addScopes", closed)
        assert G.is_cancelled_response(run(G.add_scopes([drive])))
        with pytest.raises(ValueError):
            run(G.add_scopes([]))


def test_tokens_user_and_revoke():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "getTokens", lambda cfg: {"idToken": TOKEN, "accessToken": "ya29"})
        assert run(G.get_tokens()) == {"idToken": TOKEN, "accessToken": "ya29"}

        def required(cfg):
            raise RuntimeError("SIGN_IN_REQUIRED: nobody")
        fb.on("GoogleSignIn", "getTokens", required)
        with pytest.raises(GoogleSignInError) as e:
            run(G.getTokens())
        assert e.value.code == status_codes.SIGN_IN_REQUIRED
        fb.on("GoogleSignIn", "getCurrentUser", lambda cfg: None)
        assert run(G.get_current_user()) is None
        fb.on("GoogleSignIn", "getCurrentUser", lambda cfg: {"type": "success", "data": {"user": {"id": "1"}}})
        u = run(G.getCurrentUser())
        assert u["idToken"] is None and u["user"]["email"] is None and u["scopes"] == []
        fb.on("GoogleSignIn", "hasPreviousSignIn", lambda cfg: True)
        assert run(G.has_previous_sign_in()) is True
        fb.on("GoogleSignIn", "clearCachedAccessToken", lambda t: None)
        run(G.clear_cached_access_token("ya29"))
        assert fb.calls[-1][2] == ("ya29",)
        fb.on("GoogleSignIn", "revokeAccess", lambda cfg: None)
        run(G.revokeAccess())
        assert fb.calls[-1][1] == "revokeAccess"


def test_null_presenter_code():
    G.configure(web_client_id=WEB, ios_client_id=IOS)
    with FakeBridge("ios") as fb:
        def none(cfg, o):
            raise RuntimeError("NULL_PRESENTER: no view controller")
        fb.on("GoogleSignIn", "signIn", none)
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.NULL_PRESENTER


def test_button_props():
    seen = []
    from pyxpo_google_sign_in import GoogleSigninButton
    import pyxpo_google_sign_in as mod
    real = mod._Button
    mod._Button = lambda **kw: seen.append(kw) or kw
    try:
        press = lambda _: None
        GoogleSigninButton(size=GoogleSigninButton.Size.Wide, color=GoogleSigninButton.Color.DARK, onPress=press)
        kw = seen[-1]
        assert kw["size"] == 1 and kw["color"] == 0 and kw["disabled"] is False and kw["on_press"] == press
        assert kw["style"] == {"height": 48}
        GoogleSigninButton(size=2, disabled=True, style={"margin": 4})
        assert seen[-1]["style"] == {"height": 48, "width": 48, "margin": 4} and seen[-1]["disabled"] is True
        with pytest.raises(ValueError):
            GoogleSigninButton(size=7)
    finally:
        mod._Button = real


def _plist(tmp_path, props, start=None):
    mods = Mods()
    plugin(PluginConfig({}, tmp_path, mods), props)
    return mods.apply_info_plist(start or {})


def test_plugin_writes_url_scheme(tmp_path):
    assert url_scheme(IOS) == "com.googleusercontent.apps.1234-ios"
    p = _plist(tmp_path, {"iosClientId": IOS})
    assert p["GIDClientID"] == IOS
    assert p["CFBundleURLTypes"] == [{"CFBundleURLName": "google-sign-in",
                                      "CFBundleURLSchemes": ["com.googleusercontent.apps.1234-ios"]}]
    again = _plist(tmp_path, {"iosUrlScheme": "com.googleusercontent.apps.1234-ios"}, start=p)
    assert len(again["CFBundleURLTypes"]) == 1


def test_plugin_rejects_bad_options(tmp_path):
    for props in ({}, {"iosClientId": "abc"}, {"iosUrlScheme": "myapp"}, {"iosClientId": IOS, "x": 1},
                  {"iosClientId": IOS, "iosUrlScheme": "com.googleusercontent.apps.9-other"}):
        with pytest.raises(ConfigError):
            _plist(tmp_path, props)
