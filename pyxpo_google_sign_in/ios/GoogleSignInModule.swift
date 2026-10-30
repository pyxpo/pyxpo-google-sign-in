import GoogleSignIn
import UIKit

/// Sign in with Google on the GoogleSignIn SDK, and the `PxGoogleSigninButton` view. The SDK keeps the signed-in
/// user in the keychain; `signInSilently` restores it after a restart. Errors reply as "CODE: message".
final class GoogleSignInModule: PxViewModule {
    static let moduleName = "GoogleSignIn"
    static let viewTypes = ["PxGoogleSigninButton"]

    private var photoSize: UInt = 120

    required init() {}

    func makeView(_ ctx: PxModuleContext, _ type: String, _ emit: @escaping (String, Any?) -> Void) -> PxNativeView {
        PxGoogleSigninButton(emit)
    }

    func call(_ ctx: PxModuleContext, _ method: String, _ args: [Any], _ reply: @escaping PxReply) {
        let cfg = (args.first as? [String: Any]) ?? [:]
        let gid = GIDSignIn.sharedInstance
        switch method {
        case "hasPlayServices": reply(true, nil)
        case "signIn":
            guard configure(cfg, reply) else { return }
            signIn(ctx, cfg, (args.dropFirst().first as? [String: Any]) ?? [:], reply)
        case "signInSilently":
            guard configure(cfg, reply) else { return }
            guard gid.hasPreviousSignIn() else { reply(["type": "noSavedCredentialFound"], nil); return }
            gid.restorePreviousSignIn { [weak self] user, error in
                guard let self else { return }
                if let e = error as NSError? {
                    if e.domain == kGIDSignInErrorDomain && e.code == GIDSignInError.hasNoAuthInKeychain.rawValue {
                        reply(["type": "noSavedCredentialFound"], nil)
                    } else {
                        reply(nil, Self.code(e))
                    }
                    return
                }
                guard let u = user else { reply(["type": "noSavedCredentialFound"], nil); return }
                reply(self.response(u, nil), nil)
            }
        case "addScopes":
            guard let user = gid.currentUser else { reply(nil, nil); return }
            guard let top = ctx.presenter() else { reply(nil, "NULL_PRESENTER: no view controller to present from"); return }
            let scopes = (args.dropFirst().first as? [String]) ?? []
            user.addScopes(scopes, presenting: top) { [weak self] result, error in
                guard let self else { return }
                if let e = error as NSError? {
                    if e.domain == kGIDSignInErrorDomain && e.code == GIDSignInError.scopesAlreadyGranted.rawValue {
                        reply(self.response(user, nil), nil)
                    } else {
                        reply(nil, Self.code(e))
                    }
                    return
                }
                reply(self.response(result?.user ?? user, result?.serverAuthCode), nil)
            }
        case "getTokens":
            guard let user = gid.currentUser else {
                reply(nil, "SIGN_IN_REQUIRED: getTokens() needs a signed-in user"); return
            }
            user.refreshTokensIfNeeded { fresh, error in
                if let e = error as NSError? { reply(nil, Self.code(e)); return }
                let u = fresh ?? user
                let tokens: [String: Any] = [
                    "idToken": Self.opt(u.idToken?.tokenString), "accessToken": u.accessToken.tokenString,
                ]
                reply(tokens, nil)
            }
        case "getCurrentUser":
            if let u = gid.currentUser { reply(response(u, nil), nil) } else { reply(nil, nil) }
        case "hasPreviousSignIn": reply(gid.hasPreviousSignIn(), nil)
        case "clearCachedAccessToken": reply(nil, nil) // the SDK refreshes access tokens itself
        case "revokeAccess":
            gid.disconnect { error in
                if let e = error as NSError? { reply(nil, Self.code(e)) } else { reply(nil, nil) }
            }
        case "signOut":
            gid.signOut()
            reply(nil, nil)
        default: reply(nil, "unknown native call GoogleSignIn.\(method)")
        }
    }

    /// Applies the options from `configure()`. Replies NOT_CONFIGURED and returns false without an iOS client ID.
    private func configure(_ cfg: [String: Any], _ reply: PxReply) -> Bool {
        guard let iosClient = cfg["iosClientId"] as? String, !iosClient.isEmpty else {
            reply(nil, "NOT_CONFIGURED: iosClientId is empty"); return false
        }
        func value(_ key: String) -> String? {
            guard let s = cfg[key] as? String, !s.isEmpty else { return nil }
            return s
        }
        if let size = (cfg["profileImageSize"] as? NSNumber)?.intValue, size > 0 { photoSize = UInt(size) }
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(
            clientID: iosClient, serverClientID: value("webClientId"),
            hostedDomain: value("hostedDomain"), openIDRealm: value("openIdRealm"))
        return true
    }

    private func signIn(_ ctx: PxModuleContext, _ cfg: [String: Any], _ opts: [String: Any], _ reply: @escaping PxReply) {
        guard let top = ctx.presenter() else { reply(nil, "NULL_PRESENTER: no view controller to present from"); return }
        let scopes = (cfg["scopes"] as? [String]) ?? []
        let hint = (opts["loginHint"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        GIDSignIn.sharedInstance.signIn(withPresenting: top, hint: hint, additionalScopes: scopes) { [weak self] result, error in
            guard let self else { return }
            if let e = error as NSError? { reply(nil, Self.code(e)); return }
            guard let r = result else { reply(nil, "FAILED: Google returned no result"); return }
            reply(self.response(r.user, r.serverAuthCode), nil)
        }
    }

    private func response(_ u: GIDGoogleUser, _ serverAuthCode: String?) -> [String: Any] {
        let p = u.profile
        let user: [String: Any] = [
            "id": Self.opt(u.userID), "email": Self.opt(p?.email), "name": Self.opt(p?.name),
            "givenName": Self.opt(p?.givenName), "familyName": Self.opt(p?.familyName),
            "photo": Self.opt(p?.imageURL(withDimension: photoSize)?.absoluteString),
        ]
        let data: [String: Any] = [
            "idToken": Self.opt(u.idToken?.tokenString), "serverAuthCode": Self.opt(serverAuthCode),
            "scopes": u.grantedScopes ?? [], "user": user,
        ]
        return ["type": "success", "data": data]
    }

    /// Keeps each value typed as Any; inline `String? ?? NSNull()` in a literal slows the type checker badly.
    private static func opt(_ s: String?) -> Any { s ?? NSNull() }

    private static func code(_ e: NSError) -> String {
        guard e.domain == kGIDSignInErrorDomain else { return "FAILED: \(e.localizedDescription)" }
        switch e.code {
        case GIDSignInError.canceled.rawValue: return "SIGN_IN_CANCELLED: \(e.localizedDescription)"
        case GIDSignInError.hasNoAuthInKeychain.rawValue: return "SIGN_IN_REQUIRED: \(e.localizedDescription)"
        default: return "FAILED: \(e.localizedDescription)"
        }
    }
}

/// Google's own button. `size`: 0 standard, 1 wide, 2 icon only. `color`: 0 dark, 1 light.
final class PxGoogleSigninButton: NSObject, PxNativeView {
    private let box = UIView()
    private let button = GIDSignInButton()
    private let emit: (String, Any?) -> Void

    var view: UIView { box }

    init(_ emit: @escaping (String, Any?) -> Void) {
        self.emit = emit
        super.init()
        box.backgroundColor = .clear
        button.style = .standard
        button.colorScheme = .light
        button.frame = box.bounds
        button.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        button.addTarget(self, action: #selector(pressed), for: .touchUpInside)
        box.addSubview(button)
    }

    func update(_ props: [String: Any], _ removed: [String]) {
        if let s = (props["size"] as? NSNumber)?.intValue { button.style = GIDSignInButtonStyle(rawValue: s) ?? .standard }
        if let c = (props["color"] as? NSNumber)?.intValue { button.colorScheme = c == 0 ? .dark : .light }
        if let d = props["disabled"] as? Bool { button.isEnabled = !d }
        if removed.contains("size") { button.style = .standard }
        if removed.contains("color") { button.colorScheme = .light }
        if removed.contains("disabled") { button.isEnabled = true }
    }

    func dispose() {
        button.removeTarget(nil, action: nil, for: .allEvents)
    }

    @objc private func pressed() { emit("press", nil) }
}
