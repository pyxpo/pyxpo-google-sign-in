package dev.pyxpo.modules.googlesignin

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.IntentSender
import android.os.Build
import android.os.Bundle

/**
 * Invisible activity that shows Google's consent screen for an AuthorizationClient result and hands its result
 * back to the caller. pyxpo's main activity is a plain Activity with no activity-result registry, so the module
 * starts this one with `startForResult` and reads the result in its callback.
 */
class GoogleSignInAuthActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) return // recreated while the consent screen is open: wait for its result
        val pending = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(EXTRA_PENDING, PendingIntent::class.java)
        else @Suppress("DEPRECATION") intent.getParcelableExtra(EXTRA_PENDING)
        if (pending == null) { setResult(RESULT_CANCELED); finish(); return }
        try {
            startIntentSenderForResult(pending.intentSender, REQUEST, null, 0, 0, 0)
        } catch (e: IntentSender.SendIntentException) {
            setResult(RESULT_CANCELED)
            finish()
        }
    }

    @Deprecated("Activity result API of the platform Activity")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION") super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST) return
        setResult(resultCode, data)
        finish()
    }

    companion object {
        const val EXTRA_PENDING = "dev.pyxpo.googlesignin.PENDING"
        private const val REQUEST = 0x6A1
    }
}
