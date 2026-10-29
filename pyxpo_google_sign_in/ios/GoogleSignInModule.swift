import GoogleSignIn
import UIKit

/// Sign in with Google on the GoogleSignIn SDK. Errors reply as "CODE: message" for the Python side.
final class GoogleSignInModule: PxModule {
    static let moduleName = "GoogleSignIn"

    required init() {}

    func call(_ ctx: PxModuleContext, _ method: String, _ args: [Any], _ reply: @escaping PxReply) {
        switch method {
        case "signIn": signIn(ctx, (args.first as? [String: Any]) ?? [:], reply)
        case "signOut":
            GIDSignIn.sharedInstance.signOut()
            reply(nil, nil)
        case "hasPlayServices": reply(true, nil)
        default: reply(nil, "unknown native call GoogleSignIn.\(method)")
        }
    }

    private func signIn(_ ctx: PxModuleContext, _ cfg: [String: Any], _ reply: @escaping PxReply) {
        guard let iosClient = cfg["iosClientId"] as? String, !iosClient.isEmpty else {
            reply(nil, "NOT_CONFIGURED: iosClientId is empty"); return
        }
        let web = (cfg["webClientId"] as? String) ?? ""
        let domain = (cfg["hostedDomain"] as? String) ?? ""
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(
            clientID: iosClient, serverClientID: web.isEmpty ? nil : web,
            hostedDomain: domain.isEmpty ? nil : domain, openIDRealm: nil)
        guard let top = ctx.presenter() else { reply(nil, "FAILED: no view controller to present from"); return }
        let scopes = (cfg["scopes"] as? [String]) ?? []
        GIDSignIn.sharedInstance.signIn(withPresenting: top, hint: nil, additionalScopes: scopes) { result, error in
            if let e = error as NSError? {
                if e.domain == kGIDSignInErrorDomain && e.code == GIDSignInError.canceled.rawValue {
                    reply(["type": "cancelled"], nil)
                } else {
                    reply(nil, "FAILED: \(e.localizedDescription)")
                }
                return
            }
            guard let r = result, let token = r.user.idToken?.tokenString else {
                reply(nil, "NO_ID_TOKEN: Google returned no ID token"); return
            }
            let p = r.user.profile
            let user: [String: Any] = [
                "id": r.user.userID ?? NSNull(), "email": p?.email ?? NSNull(), "name": p?.name ?? NSNull(),
                "givenName": p?.givenName ?? NSNull(), "familyName": p?.familyName ?? NSNull(),
                "photo": p?.imageURL(withDimension: 120)?.absoluteString ?? NSNull(),
            ]
            reply(["type": "success", "data": [
                "idToken": token, "serverAuthCode": r.serverAuthCode ?? NSNull(),
                "scopes": r.user.grantedScopes ?? [], "user": user,
            ]], nil)
        }
    }
}
