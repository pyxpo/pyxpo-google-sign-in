package dev.pyxpo.modules.googlesignin

import android.accounts.Account
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.view.View
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CredentialManagerCallback
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.exceptions.ClearCredentialException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.ClearTokenRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.auth.api.identity.RevokeAccessRequest
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.common.SignInButton
import com.google.android.gms.common.api.ApiException
import com.google.android.gms.common.api.CommonStatusCodes
import com.google.android.gms.common.api.Scope
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenParsingException
import dev.pyxpo.moduleapi.PxModule
import dev.pyxpo.moduleapi.PxModuleContext
import dev.pyxpo.moduleapi.PxNativeView
import dev.pyxpo.moduleapi.PxReply
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executor

/**
 * Sign in with Google: Credential Manager for authentication (the ID token), the Identity AuthorizationClient for
 * scopes, access tokens and the server auth code, and the `PxGoogleSigninButton` view. Errors reply as
 * "CODE: message" for the Python side.
 *
 * The signed-in user's profile and granted scopes (never a token) are kept in SharedPreferences, so
 * `getCurrentUser` and `hasPreviousSignIn` survive a restart. The ID token is kept in memory only.
 */
class GoogleSignInModule : PxModule() {
    override val name = "GoogleSignIn"
    override val viewTypes = setOf("PxGoogleSigninButton")

    private val main = Handler(Looper.getMainLooper())
    private val executor = Executor { main.post(it) }
    private var idToken: String? = null

    override fun makeView(ctx: PxModuleContext, type: String, emit: (name: String, value: Any?) -> Unit): PxNativeView =
        GoogleSigninButtonView(ctx.activity, emit)

    override fun call(ctx: PxModuleContext, method: String, args: JSONArray, reply: PxReply) {
        val cfg = args.optJSONObject(0) ?: JSONObject()
        when (method) {
            "hasPlayServices" -> hasPlayServices(ctx, args.optBoolean(0, true), reply)
            "signIn" -> signIn(ctx, cfg, args.optJSONObject(1) ?: JSONObject(), reply)
            "signInSilently" -> signInSilently(ctx, cfg, reply)
            "addScopes" -> addScopes(ctx, cfg, strings(args.optJSONArray(1)), reply)
            "getTokens" -> getTokens(ctx, cfg, reply)
            "getCurrentUser" -> reply(stored(ctx.context)?.let { response(it, null) }, null)
            "hasPreviousSignIn" -> reply(stored(ctx.context) != null, null)
            "clearCachedAccessToken" -> clearToken(ctx, args.optString(0), reply)
            "revokeAccess" -> revokeAccess(ctx, reply)
            "signOut" -> signOut(ctx, reply)
            else -> reply(null, "unknown native call GoogleSignIn.$method")
        }
    }

    private fun hasPlayServices(ctx: PxModuleContext, showDialog: Boolean, reply: PxReply) {
        val a = ctx.activity
        val api = GoogleApiAvailability.getInstance()
        val code = api.isGooglePlayServicesAvailable(a)
        if (code == ConnectionResult.SUCCESS) { reply(true, null); return }
        if (showDialog && api.isUserResolvableError(code)) a.runOnUiThread { api.getErrorDialog(a, code, 9001)?.show() }
        reply(false, null)
    }

    // --- authentication (Credential Manager) ---

    private fun signIn(ctx: PxModuleContext, cfg: JSONObject, opts: JSONObject, reply: PxReply) {
        val clientId = cfg.optString("webClientId")
        if (clientId.isEmpty()) { reply(null, "NOT_CONFIGURED: webClientId is empty"); return }
        val option = GetSignInWithGoogleOption.Builder(clientId).apply {
            cfg.optString("hostedDomain").takeIf { it.isNotEmpty() }?.let { setHostedDomainFilter(it) }
            opts.optString("nonce").takeIf { it.isNotEmpty() }?.let { setNonce(it) }
        }.build()
        credential(ctx, option, reply) { user, token ->
            if (needsAuthorization(cfg)) authorize(ctx, cfg, user, scopes(cfg), reply)
            else { save(ctx.context, user); reply(response(user, null, token), null) }
        }
    }

    private fun signInSilently(ctx: PxModuleContext, cfg: JSONObject, reply: PxReply) {
        val clientId = cfg.optString("webClientId")
        if (clientId.isEmpty()) { reply(null, "NOT_CONFIGURED: webClientId is empty"); return }
        val option = GetGoogleIdOption.Builder()
            .setServerClientId(clientId)
            .setFilterByAuthorizedAccounts(true)
            .setAutoSelectEnabled(true)
            .build()
        credential(ctx, option, reply, silent = true) { user, token ->
            val known = stored(ctx.context)
            // Keep scopes granted earlier; Credential Manager only knows the basic ones.
            if (known != null && known.optString("email") == user.optString("email")) {
                user.put("scopes", known.optJSONArray("scopes") ?: JSONArray(BASIC))
            }
            save(ctx.context, user)
            reply(response(user, null, token), null)
        }
    }

    private fun credential(
        ctx: PxModuleContext, option: androidx.credentials.CredentialOption, reply: PxReply, silent: Boolean = false,
        done: (user: JSONObject, idToken: String) -> Unit,
    ) {
        val a = ctx.activity
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val callback = object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
            override fun onResult(result: GetCredentialResponse) {
                val c = result.credential
                if (c !is CustomCredential || c.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                    reply(null, "FAILED: unexpected credential type ${c.type}"); return
                }
                val g = try { GoogleIdTokenCredential.createFrom(c.data) } catch (e: GoogleIdTokenParsingException) {
                    reply(null, "NO_ID_TOKEN: ${e.message}"); return
                }
                idToken = g.idToken
                val user = JSONObject()
                    // `g.id` is the email; the stable Google account ID is the token's "sub" claim.
                    .put("id", claims(g.idToken).optString("sub").ifEmpty { null } ?: JSONObject.NULL)
                    .put("email", g.id)
                    .put("name", g.displayName ?: JSONObject.NULL)
                    .put("givenName", g.givenName ?: JSONObject.NULL)
                    .put("familyName", g.familyName ?: JSONObject.NULL)
                    .put("photo", g.profilePictureUri?.toString() ?: JSONObject.NULL)
                    .put("scopes", JSONArray(BASIC))
                done(user, g.idToken)
            }

            override fun onError(e: GetCredentialException) {
                when (e) {
                    is GetCredentialCancellationException ->
                        reply(mapOf("type" to if (silent) "noSavedCredentialFound" else "cancelled"), null)
                    is NoCredentialException ->
                        if (silent) reply(mapOf("type" to "noSavedCredentialFound"), null)
                        else reply(null, "SIGN_IN_REQUIRED: ${e.message ?: "no Google account on this device"}")
                    else -> reply(null, "FAILED: ${e.type}: ${e.message}")
                }
            }
        }
        a.runOnUiThread { CredentialManager.create(a).getCredentialAsync(a, request, null, executor, callback) }
    }

    // --- authorization (scopes, access token, server auth code) ---

    private fun addScopes(ctx: PxModuleContext, cfg: JSONObject, extra: List<String>, reply: PxReply) {
        val user = stored(ctx.context) ?: run { reply(null, null); return }
        val all = (strings(user.optJSONArray("scopes")) + scopes(cfg) + extra).distinct()
        authorize(ctx, cfg, user, all, reply)
    }

    private fun getTokens(ctx: PxModuleContext, cfg: JSONObject, reply: PxReply) {
        val user = stored(ctx.context)
            ?: run { reply(null, "SIGN_IN_REQUIRED: getTokens() needs a signed-in user"); return }
        val token = idToken
        val finish = { id: String ->
            requestAuthorization(ctx, cfg, user, strings(user.optJSONArray("scopes")), offline = false) { r, err ->
                if (err != null) reply(null, err)
                else reply(mapOf("idToken" to id, "accessToken" to r!!.accessToken), null)
            }
        }
        // The ID token lives in memory only; after a restart get a fresh one without UI.
        if (token != null && !expired(token)) { finish(token); return }
        signInSilently(ctx, cfg) { v, e ->
            val fresh = idToken
            when {
                e != null -> reply(null, e)
                fresh == null || (v as? Map<*, *>)?.get("type") == "noSavedCredentialFound" ->
                    reply(null, "SIGN_IN_REQUIRED: the saved Google account is no longer available")
                else -> finish(fresh)
            }
        }
    }

    private fun authorize(ctx: PxModuleContext, cfg: JSONObject, user: JSONObject, want: List<String>, reply: PxReply) {
        requestAuthorization(ctx, cfg, user, want, offline = cfg.optBoolean("offlineAccess")) { r, err ->
            if (err != null) { reply(null, err); return@requestAuthorization }
            val granted = (r!!.grantedScopes ?: emptyList()).ifEmpty { want }
            user.put("scopes", JSONArray((BASIC + granted).distinct()))
            save(ctx.context, user)
            reply(response(user, r.serverAuthCode, idToken), null)
        }
    }

    /** Runs AuthorizationClient.authorize, showing Google's consent screen through [GoogleSignInAuthActivity]. */
    private fun requestAuthorization(
        ctx: PxModuleContext, cfg: JSONObject, user: JSONObject, want: List<String>, offline: Boolean,
        done: (AuthorizationResult?, String?) -> Unit,
    ) {
        val a = ctx.activity
        val webClient = cfg.optString("webClientId")
        val request = AuthorizationRequest.Builder()
            .setRequestedScopes((BASIC + want).distinct().map { Scope(it) })
            .apply {
                user.optString("email").takeIf { it.isNotEmpty() }?.let { setAccount(Account(it, ACCOUNT_TYPE)) }
                cfg.optString("hostedDomain").takeIf { it.isNotEmpty() }?.let { filterByHostedDomain(it) }
                if (offline && webClient.isNotEmpty()) requestOfflineAccess(webClient, cfg.optBoolean("forceCodeForRefreshToken"))
            }
            .build()
        val client = Identity.getAuthorizationClient(a)
        client.authorize(request)
            .addOnSuccessListener(executor) { r ->
                val pending = r.pendingIntent
                if (!r.hasResolution() || pending == null) { done(r, null); return@addOnSuccessListener }
                val intent = Intent(a, GoogleSignInAuthActivity::class.java)
                    .putExtra(GoogleSignInAuthActivity.EXTRA_PENDING, pending)
                try {
                    ctx.startForResult(intent) { code, data ->
                        if (code != Activity.RESULT_OK) { done(null, "SIGN_IN_CANCELLED: the user closed the consent screen"); return@startForResult }
                        try { done(client.getAuthorizationResultFromIntent(data), null) }
                        catch (e: ApiException) { done(null, apiError(e)) }
                    }
                } catch (e: Throwable) {
                    done(null, "FAILED: could not open the consent screen: ${e.message}")
                }
            }
            .addOnFailureListener(executor) { e -> done(null, if (e is ApiException) apiError(e) else "FAILED: ${e.message}") }
    }

    private fun clearToken(ctx: PxModuleContext, token: String, reply: PxReply) {
        if (token.isEmpty()) { reply(null, "FAILED: clearCachedAccessToken() needs a token"); return }
        Identity.getAuthorizationClient(ctx.activity)
            .clearToken(ClearTokenRequest.builder().setToken(token).build())
            .addOnSuccessListener(executor) { reply(null, null) }
            .addOnFailureListener(executor) { e -> reply(null, "FAILED: ${e.message}") }
    }

    private fun revokeAccess(ctx: PxModuleContext, reply: PxReply) {
        val user = stored(ctx.context)
        val email = user?.optString("email").orEmpty()
        if (email.isEmpty()) { clearState(ctx, reply); return }
        val request = RevokeAccessRequest.builder()
            .setAccount(Account(email, ACCOUNT_TYPE))
            .setScopes((BASIC + strings(user?.optJSONArray("scopes"))).distinct().map { Scope(it) })
            .build()
        Identity.getAuthorizationClient(ctx.activity).revokeAccess(request)
            .addOnSuccessListener(executor) { clearState(ctx, reply) }
            .addOnFailureListener(executor) { e -> reply(null, if (e is ApiException) apiError(e) else "FAILED: ${e.message}") }
    }

    private fun signOut(ctx: PxModuleContext, reply: PxReply) = clearState(ctx, reply)

    /** Forgets the user here and in Credential Manager, so the next sign-in shows the account picker. */
    private fun clearState(ctx: PxModuleContext, reply: PxReply) {
        idToken = null
        prefs(ctx.context).edit().clear().apply()
        CredentialManager.create(ctx.context).clearCredentialStateAsync(
            ClearCredentialStateRequest(), null, executor,
            object : CredentialManagerCallback<Void?, ClearCredentialException> {
                override fun onResult(result: Void?) = reply(null, null)
                override fun onError(e: ClearCredentialException) = reply(null, "FAILED: ${e.message}")
            },
        )
    }

    // --- helpers ---

    private fun needsAuthorization(cfg: JSONObject) =
        cfg.optBoolean("offlineAccess") || scopes(cfg).any { it !in BASIC }

    private fun scopes(cfg: JSONObject) = strings(cfg.optJSONArray("scopes"))

    private fun response(user: JSONObject, serverAuthCode: String?, token: String? = idToken): Map<String, Any?> {
        val u = JSONObject(user.toString()).apply { remove("scopes") }
        return mapOf("type" to "success", "data" to mapOf(
            "idToken" to token, "serverAuthCode" to serverAuthCode,
            "scopes" to strings(user.optJSONArray("scopes")), "user" to u,
        ))
    }

    private fun apiError(e: ApiException) = when (e.statusCode) {
        CommonStatusCodes.CANCELED -> "SIGN_IN_CANCELLED: ${e.message}"
        CommonStatusCodes.SIGN_IN_REQUIRED -> "SIGN_IN_REQUIRED: ${e.message}"
        CommonStatusCodes.NETWORK_ERROR -> "FAILED: network error: ${e.message}"
        else -> "FAILED: ${e.statusCode}: ${e.message}"
    }

    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun stored(c: Context): JSONObject? =
        prefs(c).getString(KEY_USER, null)?.let { runCatching { JSONObject(it) }.getOrNull() }

    private fun save(c: Context, user: JSONObject) {
        prefs(c).edit().putString(KEY_USER, user.toString()).apply()
    }

    private fun claims(jwt: String): JSONObject = runCatching {
        val part = jwt.split(".")[1]
        JSONObject(String(Base64.decode(part, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING), Charsets.UTF_8))
    }.getOrElse { JSONObject() }

    /** True when the token expires within a minute. */
    private fun expired(jwt: String): Boolean {
        val exp = claims(jwt).optLong("exp", 0)
        return exp == 0L || exp * 1000 - 60_000 < System.currentTimeMillis()
    }

    private fun strings(a: JSONArray?): List<String> =
        if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optString(it).ifEmpty { null } }

    companion object {
        private const val PREFS = "dev.pyxpo.googlesignin"
        private const val KEY_USER = "user"
        private const val ACCOUNT_TYPE = "com.google"
        private val BASIC = listOf("openid", "email", "profile")
    }
}

/** Google's own sign-in button. `size`: 0 standard, 1 wide, 2 icon only. `color`: 0 dark, 1 light. */
private class GoogleSigninButtonView(ctx: Context, private val emit: (String, Any?) -> Unit) : PxNativeView {
    private val button = SignInButton(ctx).apply {
        setSize(SignInButton.SIZE_STANDARD)
        setColorScheme(SignInButton.COLOR_LIGHT)
        setOnClickListener { emit("press", null) }
    }

    override val view: View get() = button

    override fun update(props: JSONObject, removed: Set<String>) {
        if (props.has("size")) button.setSize(props.optInt("size").coerceIn(0, 2))
        if (props.has("color")) button.setColorScheme(if (props.optInt("color") == 0) SignInButton.COLOR_DARK else SignInButton.COLOR_LIGHT)
        if (props.has("disabled")) button.isEnabled = !props.optBoolean("disabled")
        if ("size" in removed) button.setSize(SignInButton.SIZE_STANDARD)
        if ("color" in removed) button.setColorScheme(SignInButton.COLOR_LIGHT)
        if ("disabled" in removed) button.isEnabled = true
    }

    override fun dispose() = button.setOnClickListener(null)
}
