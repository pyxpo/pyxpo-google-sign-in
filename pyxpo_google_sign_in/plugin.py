"""Config plugin for Sign in with Google on iOS: the client ID and its reversed URL scheme in Info.plist.

    [tool.pyxpo]
    modules = ["google-sign-in"]
    plugins = [["pyxpo_google_sign_in.plugin", {"iosClientId": "1234-abc.apps.googleusercontent.com"}]]

Options:
- `iosClientId`: the OAuth client of type iOS. The plugin writes `GIDClientID` and adds the reversed client ID
  (`com.googleusercontent.apps.1234-abc`) to `CFBundleURLTypes`; the GoogleSignIn SDK stops the app without it.
- `iosUrlScheme`: the reversed client ID itself, when you prefer to give it instead of `iosClientId`.

Android needs no plugin options: Credential Manager takes the web client ID at run time, and Google matches the
app by its package name and signing certificate (SHA-1) in the Android OAuth client.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from pyxpo.app_config import ConfigError
from pyxpo.config_plugins import PluginConfig, with_info_plist

SUFFIX = ".apps.googleusercontent.com"
PREFIX = "com.googleusercontent.apps."
CLIENT_RE = re.compile(r"^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$")
SCHEME_RE = re.compile(r"^com\.googleusercontent\.apps\.[0-9]+-[a-z0-9]+$")


def _fail(msg: str) -> ConfigError:
    return ConfigError("pyxpo_google_sign_in.plugin: " + msg)


def url_scheme(ios_client_id: str) -> str:
    """`1234-abc.apps.googleusercontent.com` -> `com.googleusercontent.apps.1234-abc`."""
    return PREFIX + ios_client_id[: -len(SUFFIX)]


def plugin(config: PluginConfig, props: Dict[str, Any]) -> PluginConfig:
    props = dict(props or {})
    unknown = sorted(set(props) - {"iosClientId", "iosUrlScheme"})
    if unknown:
        raise _fail("unknown options %s (known: iosClientId, iosUrlScheme)" % unknown)
    client = props.get("iosClientId")
    scheme = props.get("iosUrlScheme")
    if client is None and scheme is None:
        raise _fail("give iosClientId (the OAuth client of type iOS)")
    if client is not None and (not isinstance(client, str) or not CLIENT_RE.match(client)):
        raise _fail("iosClientId must look like 1234-abc.apps.googleusercontent.com, got %r" % (client,))
    if scheme is not None and (not isinstance(scheme, str) or not SCHEME_RE.match(scheme)):
        raise _fail("iosUrlScheme must look like com.googleusercontent.apps.1234-abc, got %r" % (scheme,))
    if client and scheme and url_scheme(client) != scheme:
        raise _fail("iosUrlScheme %r is not the reversed iosClientId %r" % (scheme, client))
    scheme = scheme or url_scheme(client)

    def info_plist(d: Dict[str, Any]) -> None:
        if client:
            d["GIDClientID"] = client
        types = d.setdefault("CFBundleURLTypes", [])
        if not any(scheme in (t.get("CFBundleURLSchemes") or []) for t in types):
            types.append({"CFBundleURLName": "google-sign-in", "CFBundleURLSchemes": [scheme]})

    with_info_plist(config, info_plist)
    return config
