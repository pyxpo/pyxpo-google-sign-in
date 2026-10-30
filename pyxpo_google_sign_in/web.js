// pyxpo-google-sign-in in the browser and the desktop window: Google Identity Services.
// signIn shows a small sheet with Google's own button; the credential callback gives the ID token.
// signInSilently uses One Tap with auto select. Access tokens and extra scopes come from the GIS token client.
// The page origin must be an authorized JavaScript origin of the web client in Google Cloud console.
(function () {
  "use strict";

  const GIS = "https://accounts.google.com/gsi/client";
  const FLAG = "pyxpo.googleSignIn.user";   // the last user's profile (never a token), for hasPreviousSignIn
  const BASIC = ["openid", "email", "profile"];
  let loading = null;
  let pending = null;   // {resolve, reject, sheet}
  let current = null;   // {idToken, serverAuthCode, scopes, user}
  let access = null;    // {token, expires, scopes}

  function load() {
    if (window.google && window.google.accounts && window.google.accounts.id) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = GIS;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => { loading = null; reject(new Error("FAILED: could not load Google Identity Services")); };
      document.head.appendChild(s);
    });
    return loading;
  }

  function claims(token) {
    try {
      const b = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(b))));
    } catch (e) {
      return {};
    }
  }

  function remember(user) {
    try {
      if (user) localStorage.setItem(FLAG, JSON.stringify(user)); else localStorage.removeItem(FLAG);
    } catch (e) { /* storage blocked: hasPreviousSignIn reports false */ }
  }

  function saved() {
    try { return JSON.parse(localStorage.getItem(FLAG) || "null"); } catch (e) { return null; }
  }

  function success(credential) {
    const c = claims(credential);
    const scopes = current && current.user.id === c.sub ? current.scopes : BASIC.slice();
    current = { idToken: credential, serverAuthCode: null, scopes, user: {
      id: c.sub || null, email: c.email || null, name: c.name || null, givenName: c.given_name || null,
      familyName: c.family_name || null, photo: c.picture || null } };
    remember(current.user);
    return { type: "success", data: current };
  }

  function close(result, error) {
    const p = pending;
    pending = null;
    if (!p) return;
    if (p.sheet) p.sheet.remove();
    if (error) p.reject(new Error(error)); else p.resolve(result);
  }

  function sheet() {
    const back = document.createElement("div");
    back.style.cssText = "position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;" +
      "justify-content:center;background:rgba(0,0,0,.45);font-family:system-ui,sans-serif";
    const card = document.createElement("div");
    card.style.cssText = "background:#fff;color:#111;border-radius:16px;padding:24px;min-width:280px;" +
      "display:flex;flex-direction:column;gap:16px;align-items:center;box-shadow:0 12px 40px rgba(0,0,0,.25)";
    const slot = document.createElement("div");
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    cancel.style.cssText = "border:0;background:none;color:#555;font-size:14px;cursor:pointer;padding:6px 12px";
    cancel.onclick = () => close({ type: "cancelled" });
    back.onclick = (e) => { if (e.target === back) close({ type: "cancelled" }); };
    card.append(slot, cancel);
    back.appendChild(card);
    document.body.appendChild(back);
    return { back, slot };
  }

  function idOptions(cfg, extra) {
    const opts = Object.assign({ client_id: cfg.webClientId }, extra);
    if (cfg.hostedDomain) opts.hd = cfg.hostedDomain;
    return opts;
  }

  function signIn(cfg, o) {
    return load().then(() => new Promise((resolve, reject) => {
      const { back, slot } = sheet();
      pending = { resolve, reject, sheet: back };
      const extra = { callback: (r) => close(success(r.credential)) };
      if (o.nonce) extra.nonce = o.nonce;
      if (o.loginHint) extra.login_hint = o.loginHint;
      window.google.accounts.id.initialize(idOptions(cfg, extra));
      window.google.accounts.id.renderButton(slot, { theme: "outline", size: "large", text: "continue_with",
        shape: "pill", width: 260 });
    }));
  }

  function signInSilently(cfg) {
    if (!saved()) return Promise.resolve({ type: "noSavedCredentialFound" });
    return load().then(() => new Promise((resolve, reject) => {
      pending = { resolve, reject, sheet: null };
      window.google.accounts.id.initialize(idOptions(cfg, {
        auto_select: true, callback: (r) => close(success(r.credential)),
      }));
      window.google.accounts.id.prompt((n) => {
        if (n.isNotDisplayed() || n.isSkippedMoment() || n.isDismissedMoment()) close({ type: "noSavedCredentialFound" });
      });
    }));
  }

  // GIS token client: a popup only when the user has not granted these scopes yet.
  function token(cfg, scopes) {
    return load().then(() => new Promise((resolve, reject) => {
      const all = Array.from(new Set(BASIC.concat(cfg.scopes || [], scopes || [])));
      const client = window.google.accounts.oauth2.initTokenClient({
        client_id: cfg.webClientId, scope: all.join(" "), hint: current ? current.user.email : undefined,
        hosted_domain: cfg.hostedDomain || undefined,
        callback: (r) => {
          if (r.error) { reject(new Error((r.error === "access_denied" ? "SIGN_IN_CANCELLED: " : "FAILED: ") + r.error)); return; }
          access = { token: r.access_token, expires: Date.now() + (Number(r.expires_in) || 3600) * 1000,
            scopes: all.filter((s) => window.google.accounts.oauth2.hasGrantedAllScopes(r, s)) };
          resolve(access);
        },
        error_callback: (e) => reject(new Error((e && e.type === "popup_closed" ? "SIGN_IN_CANCELLED: " : "FAILED: ") +
          (e && e.message || "token request failed"))),
      });
      client.requestAccessToken({ prompt: "" });
    }));
  }

  pyxpoPage.defineModule("GoogleSignIn", (method, args) => {
    const cfg = args[0] || {};
    switch (method) {
      case "hasPlayServices":
        return true;
      case "hasPreviousSignIn":
        return !!saved();
      case "getCurrentUser":
        return current ? { type: "success", data: current } : null;
      case "signIn":
        if (!cfg.webClientId) return Promise.reject(new Error("NOT_CONFIGURED: webClientId is empty"));
        if (pending) return Promise.reject(new Error("IN_PROGRESS: a sign-in is already in progress"));
        return signIn(cfg, args[1] || {});
      case "signInSilently":
        if (!cfg.webClientId) return Promise.reject(new Error("NOT_CONFIGURED: webClientId is empty"));
        if (pending) return Promise.reject(new Error("IN_PROGRESS: a sign-in is already in progress"));
        return signInSilently(cfg);
      case "addScopes":
        if (!current) return null;
        return token(cfg, args[1] || []).then((a) => {
          current.scopes = Array.from(new Set(current.scopes.concat(a.scopes)));
          return { type: "success", data: current };
        });
      case "getTokens":
        if (!current) return Promise.reject(new Error("SIGN_IN_REQUIRED: getTokens() needs a signed-in user"));
        if (access && access.expires - 60000 > Date.now()) {
          return { idToken: current.idToken, accessToken: access.token };
        }
        return token(cfg, current.scopes).then((a) => ({ idToken: current.idToken, accessToken: a.token }));
      case "clearCachedAccessToken":
        if (access && access.token === args[0]) access = null;
        return null;
      case "revokeAccess": {
        const email = current ? current.user.email : (saved() || {}).email;
        const tok = access && access.token;
        current = null; access = null; remember(null);
        if (!window.google || !window.google.accounts) return null;
        if (tok) window.google.accounts.oauth2.revoke(tok, () => {});
        if (!email) return null;
        return new Promise((resolve) => window.google.accounts.id.revoke(email, () => resolve(null)));
      }
      case "signOut":
        current = null; access = null; remember(null);
        if (window.google && window.google.accounts) window.google.accounts.id.disableAutoSelect();
        return null;
      default:
        return Promise.reject(new Error("unknown native call GoogleSignIn." + method));
    }
  });

  // Google-branded button that reports presses; the app then calls sign_in(). size: 0 standard, 1 wide,
  // 2 icon only. color: 0 dark, 1 light.
  const G = '<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">' +
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>' +
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>' +
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>' +
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>';

  pyxpoPage.defineView("PxGoogleSigninButton", (el, emit) => {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("aria-label", "Sign in with Google");
    b.onclick = () => emit("press", null);
    el.appendChild(b);
    const state = { size: 0, color: 1, disabled: false };
    function draw() {
      const dark = state.color === 0;
      const icon = state.size === 2;
      b.disabled = state.disabled;
      b.innerHTML = '<span style="display:flex;background:#fff;border-radius:2px;padding:' + (dark ? "8px" : "0") + '">' +
        G + "</span>" + (icon ? "" : "<span>" + (state.size === 1 ? "Sign in with Google" : "Sign in") + "</span>");
      b.style.cssText = "display:inline-flex;align-items:center;justify-content:center;gap:12px;box-sizing:border-box;" +
        "width:100%;height:100%;min-height:40px;padding:" + (dark ? "0 12px 0 1px" : "0 12px") + ";border-radius:4px;" +
        "font:500 14px Roboto,system-ui,sans-serif;cursor:pointer;" +
        (dark ? "background:#4285F4;color:#fff;border:0;" : "background:#fff;color:#1f1f1f;border:1px solid #dadce0;") +
        (state.disabled ? "opacity:.6;cursor:default;" : "");
    }
    draw();
    return {
      update(props, removed) {
        if ("size" in props) state.size = Number(props.size) || 0;
        if ("color" in props) state.color = Number(props.color) === 0 ? 0 : 1;
        if ("disabled" in props) state.disabled = !!props.disabled;
        for (const k of removed || []) if (k in state) state[k] = { size: 0, color: 1, disabled: false }[k];
        draw();
      },
      dispose() { b.onclick = null; },
    };
  });
})();
