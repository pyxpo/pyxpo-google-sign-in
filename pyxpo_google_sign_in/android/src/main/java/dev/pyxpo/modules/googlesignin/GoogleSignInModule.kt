package dev.pyxpo.modules.googlesignin

import android.os.Handler
import android.os.Looper
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
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenParsingException
import dev.pyxpo.moduleapi.PxModule
import dev.pyxpo.moduleapi.PxModuleContext
import dev.pyxpo.moduleapi.PxReply
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executor

/** Sign in with Google on Credential Manager. Errors reply as "CODE: message" for the Python side. */
class GoogleSignInModule : PxModule() {
    override val name = "GoogleSignIn"

    private val main = Handler(Looper.getMainLooper())
    private val executor = Executor { main.post(it) }

    override fun call(ctx: PxModuleContext, method: String, args: JSONArray, reply: PxReply) {
        when (method) {
            "hasPlayServices" -> hasPlayServices(ctx, args.optBoolean(0, true), reply)
            "signIn" -> signIn(ctx, args.optJSONObject(0) ?: JSONObject(), reply)
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

    private fun signIn(ctx: PxModuleContext, cfg: JSONObject, reply: PxReply) {
        val a = ctx.activity
        val clientId = cfg.optString("webClientId")
        if (clientId.isEmpty()) { reply(null, "NOT_CONFIGURED: webClientId is empty"); return }
        val option = GetSignInWithGoogleOption.Builder(clientId).apply {
            val domain = cfg.optString("hostedDomain")
            if (domain.isNotEmpty()) setHostedDomainFilter(domain)
        }.build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val callback = object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
            override fun onResult(result: GetCredentialResponse) {
                val c = result.credential
                if (c !is CustomCredential || c.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                    reply(null, "FAILED: unexpected credential type ${c.type}"); return
                }
                try {
                    val g = GoogleIdTokenCredential.createFrom(c.data)
                    val user = mapOf(
                        "id" to g.id, "email" to g.id, "name" to g.displayName, "givenName" to g.givenName,
                        "familyName" to g.familyName, "photo" to g.profilePictureUri?.toString(),
                    )
                    reply(mapOf("type" to "success", "data" to mapOf("idToken" to g.idToken, "user" to user)), null)
                } catch (e: GoogleIdTokenParsingException) {
                    reply(null, "NO_ID_TOKEN: ${e.message}")
                }
            }

            override fun onError(e: GetCredentialException) {
                when (e) {
                    is GetCredentialCancellationException -> reply(mapOf("type" to "cancelled"), null)
                    is NoCredentialException -> reply(null, "SIGN_IN_REQUIRED: ${e.message ?: "no Google account"}")
                    else -> reply(null, "FAILED: ${e.type}: ${e.message}")
                }
            }
        }
        a.runOnUiThread { CredentialManager.create(a).getCredentialAsync(a, request, null, executor, callback) }
    }

    private fun signOut(ctx: PxModuleContext, reply: PxReply) {
        CredentialManager.create(ctx.activity).clearCredentialStateAsync(
            ClearCredentialStateRequest(), null, executor,
            object : CredentialManagerCallback<Void?, ClearCredentialException> {
                override fun onResult(result: Void?) = reply(null, null)
                override fun onError(e: ClearCredentialException) = reply(null, "FAILED: ${e.message}")
            },
        )
    }
}
