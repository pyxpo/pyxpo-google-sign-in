// pyxpo-google-sign-in in the browser and the desktop window: Google Identity Services.
// sign-in shows a small sheet with Google's own button; the credential callback gives the ID token.
// The page origin must be an authorized JavaScript origin of the web client in Google Cloud console.
(function () {
  "use strict";

  const GIS = "https://accounts.google.com/gsi/client";
  let loading = null;
  let pending = null;   // {resolve, reject, sheet}

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

  function close(result, error) {
    const p = pending;
    pending = null;
    if (!p) return;
    p.sheet.remove();
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

  pyxpoPage.defineModule("GoogleSignIn", (method, args) => {
    switch (method) {
      case "hasPlayServices":
        return true;
      case "signOut":
        if (window.google && window.google.accounts) window.google.accounts.id.disableAutoSelect();
        return null;
      case "signIn": {
        const cfg = args[0] || {};
        if (!cfg.webClientId) return Promise.reject(new Error("NOT_CONFIGURED: webClientId is empty"));
        if (pending) return Promise.reject(new Error("IN_PROGRESS: a sign-in is already in progress"));
        return load().then(() => new Promise((resolve, reject) => {
          const { back, slot } = sheet();
          pending = { resolve, reject, sheet: back };
          const opts = {
            client_id: cfg.webClientId,
            callback: (r) => {
              const c = claims(r.credential);
              close({ type: "success", data: { idToken: r.credential, user: {
                id: c.sub || null, email: c.email || null, name: c.name || null, givenName: c.given_name || null,
                familyName: c.family_name || null, photo: c.picture || null } } });
            },
          };
          if (cfg.hostedDomain) opts.hd = cfg.hostedDomain;
          window.google.accounts.id.initialize(opts);
          window.google.accounts.id.renderButton(slot, { theme: "outline", size: "large", text: "continue_with",
            shape: "pill", width: 260 });
        }));
      }
      default:
        return Promise.reject(new Error("unknown native call GoogleSignIn." + method));
    }
  });
})();
