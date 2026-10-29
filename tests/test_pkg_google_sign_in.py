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
        fb.on("GoogleSignIn", "signIn", lambda cfg: {"type": "success", "data": {
            "idToken": TOKEN, "user": {"email": "a@b.co", "name": "A B"}}})
        res = run(G.GoogleSignin.signIn())
        assert G.is_success_response(res)
        assert res["data"]["idToken"] == TOKEN
        assert res["data"]["user"]["email"] == "a@b.co" and res["data"]["user"]["photo"] is None
        assert fb.calls[0][2][0]["webClientId"] == WEB


def test_cancel_and_no_token():
    G.configure(web_client_id=WEB, ios_client_id=IOS)
    with FakeBridge("ios") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg: {"type": "cancelled"})
        assert G.is_cancelled_response(run(G.sign_in()))

        def cancelled(cfg):
            raise RuntimeError("SIGN_IN_CANCELLED: closed")
        fb.on("GoogleSignIn", "signIn", cancelled)
        assert run(G.sign_in()) == {"type": "cancelled", "data": None}
        fb.on("GoogleSignIn", "signIn", lambda cfg: {"type": "success", "data": {"user": {}}})
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.NO_ID_TOKEN


def test_native_error_codes():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        def fail(cfg):
            raise RuntimeError("SIGN_IN_REQUIRED: no Google account")
        fb.on("GoogleSignIn", "signIn", fail)
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.SIGN_IN_REQUIRED and str(e.value) == "no Google account"
        assert G.is_error_with_code(e.value)

        def plain(cfg):
            raise RuntimeError("boom")
        fb.on("GoogleSignIn", "signIn", plain)
        with pytest.raises(GoogleSignInError) as e:
            run(G.sign_in())
        assert e.value.code == status_codes.FAILED
        assert G._busy is False


def test_in_progress():
    G.configure(web_client_id=WEB)
    with FakeBridge("android") as fb:
        fb.on("GoogleSignIn", "signIn", lambda cfg: {"type": "cancelled"})
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
        fb.on("GoogleSignIn", "signOut", lambda: None)
        run(G.sign_out())
        assert fb.calls[-1][1] == "signOut"


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
