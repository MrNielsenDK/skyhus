import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import OneDriveGui
import "../components" as UI

// Bekræftelsen, før applikationen stopper en service under --resync (feature 0010).
UI.Sheet {
    id: sheet
    objectName: "confirmCancelResync"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.cancelResyncAccountName !== ""
    title: "Afbryd resync?"

    Text {
        objectName: "confirmCancelResyncText"
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Kontoen \"" + sheet.controller.cancelResyncAccountName
              + "\" synkroniserer ikke, før du starter en ny resync. En ny resync begynder forfra."
        font: Theme.body
        color: Theme.textPrimary
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Applikationen stopper servicen. Filer, som klienten har hentet, bliver liggende."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Annullér"
            onClicked: sheet.controller.dismissCancelResync()
        },
        UI.SecondaryButton {
            objectName: "confirmCancelResyncButton"
            destructive: true
            text: "Afbryd resync"
            onClicked: sheet.controller.confirmCancelResync()
        }
    ]
}
