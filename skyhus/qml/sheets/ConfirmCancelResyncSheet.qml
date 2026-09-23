import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The confirmation before the application stops a service during --resync (feature 0010).
UI.Sheet {
    id: sheet
    objectName: "confirmCancelResync"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.cancelResyncAccountName !== ""
    title: "Stop resync?"

    Text {
        objectName: "confirmCancelResyncText"
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "The account \"" + sheet.controller.cancelResyncAccountName
              + "\" does not sync until you start a new resync. A new resync starts from the beginning."
        font: Theme.body
        color: Theme.textPrimary
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Skyhus stops the service. Files that the client has downloaded stay where they are."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Cancel"
            onClicked: sheet.controller.dismissCancelResync()
        },
        UI.SecondaryButton {
            objectName: "confirmCancelResyncButton"
            destructive: true
            text: "Stop resync"
            onClicked: sheet.controller.confirmCancelResync()
        }
    ]
}
