# Changelog

## Unreleased

## 0.1.0a2

- Full @react-native-google-signin/google-signin API: `sign_in_silently`, `add_scopes`, `get_tokens`,
  `get_current_user`, `has_previous_sign_in`, `clear_cached_access_token`, `revoke_access`,
  `is_no_saved_credential_found_response`, `status_codes.NULL_PRESENTER`.
- `sign_in(login_hint=..., nonce=...)`; `configure` takes `force_code_for_refresh_token`, `profile_image_size`,
  `openid_realm` and `account_name`.
- `GoogleSigninButton` view: Google's native button on Android and iOS, a branded button on the web.
- Android: scopes, access tokens and `serverAuthCode` through AuthorizationClient, with Google's consent screen.
  `user.id` is now the stable Google account ID instead of the email.
- Native contract 2.

## 0.1.0a1

- First release: `configure`, `has_play_services`, `sign_in`, `sign_out`, `status_codes` and the
  `GoogleSignInError` codes. Android on Credential Manager, iOS on GoogleSignIn 8, the web and the desktop window on
  Google Identity Services.
- Config plugin `pyxpo_google_sign_in.plugin` writes `GIDClientID` and the reversed client ID URL scheme on iOS.
