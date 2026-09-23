import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// Vinduet venter på handlinger, der stopper eller starter en service (feature 0008).
UI.Sheet {
    id: sheet
    objectName: "closingSheet"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.closing && !warning.visible
    title: "Applikationen lukker, når arbejdet er færdigt"

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingM

        BusyIndicator {
            Layout.alignment: Qt.AlignTop
            running: sheet.visible
            palette.dark: Theme.textSecondary
        }
        Text {
            objectName: "closingText"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            wrapMode: Text.Wrap
            text: sheet.controller.busyText
            font: Theme.body
            color: Theme.textPrimary
        }
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Vinduet lukker af sig selv, når handlingen er færdig."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            objectName: "forceCloseButton"
            text: "Luk alligevel"
            onClicked: warning.open()
        }
    ]

    // Advarslen, før vinduet lukker midt i en handling.
    UI.Sheet {
        id: warning
        objectName: "forceCloseWarning"

        closePolicy: T.Popup.NoAutoClose
        title: "Luk alligevel?"

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingS

            UI.Icon {
                Layout.alignment: Qt.AlignTop
                name: "triangle-alert"
                color: Theme.warning
            }
            Text {
                objectName: "forceCloseWarningText"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Servicen kan blive stående stoppet, hvis du lukker nu. "
                      + "Start den igen i kortet \"Service\", næste gang du åbner applikationen."
                font: Theme.body
                color: Theme.textPrimary
            }
        }

        buttons: [
            UI.SecondaryButton {
                text: "Vent"
                onClicked: warning.close()
            },
            UI.SecondaryButton {
                objectName: "forceCloseConfirmButton"
                destructive: true
                text: "Luk nu"
                onClicked: sheet.controller.forceClose()
            }
        ]
    }
}
