import QtQuick
import QtWebEngine

// Viser Microsofts login-side og fanger videresendelsen til nativeclient.
Item {
    id: sheet

    property string authUrl
    readonly property string nativeClientUrl: "https://login.microsoftonline.com/common/oauth2/nativeclient"
    property bool captured: false

    signal redirectCaptured(string url)

    function capture(url) {
        var text = url.toString()
        if (sheet.captured || !text.startsWith(sheet.nativeClientUrl))
            return false
        sheet.captured = true
        sheet.redirectCaptured(text)
        return true
    }

    // En ny profil uden lagring. Så logger en tidligere konto ikke ind automatisk.
    WebEngineProfile {
        id: privateProfile
        offTheRecord: true
    }

    WebEngineView {
        id: view
        anchors.fill: parent
        profile: privateProfile
        url: sheet.authUrl

        onNavigationRequested: function(request) {
            if (sheet.capture(request.url))
                request.reject()
        }
        onUrlChanged: sheet.capture(url)
    }
}
