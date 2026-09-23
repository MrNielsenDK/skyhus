import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The confirmation before the application restarts a service with --resync.
UI.Sheet {
    id: sheet
    objectName: "confirmResync"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.resyncAccountName !== ""
    title: "Restart with resync"

    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "The client compares all of the account \"" + sheet.controller.resyncAccountName
              + "\" with OneDrive again. This can take a long time for a large account."
        font: Theme.body
        color: Theme.textPrimary
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Skyhus restarts the service 1 time with --resync --resync-auth. After that, the service runs as before."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Cancel"
            onClicked: sheet.controller.cancelResync()
        },
        UI.PrimaryButton {
            objectName: "confirmResyncButton"
            text: "Restart with resync"
            onClicked: sheet.controller.confirmResync()
        }
    ]
}
