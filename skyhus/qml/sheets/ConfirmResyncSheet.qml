import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// Bekræftelsen, før applikationen genstarter en service med --resync.
UI.Sheet {
    id: sheet
    objectName: "confirmResync"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.resyncAccountName !== ""
    title: "Genstart med resync"

    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Klienten sammenligner hele kontoen \"" + sheet.controller.resyncAccountName
              + "\" med OneDrive igen. Det kan tage lang tid for en stor konto."
        font: Theme.body
        color: Theme.textPrimary
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Applikationen genstarter servicen 1 gang med --resync --resync-auth. Derefter kører servicen som før."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Annullér"
            onClicked: sheet.controller.cancelResync()
        },
        UI.PrimaryButton {
            objectName: "confirmResyncButton"
            text: "Genstart med resync"
            onClicked: sheet.controller.confirmResync()
        }
    ]
}
