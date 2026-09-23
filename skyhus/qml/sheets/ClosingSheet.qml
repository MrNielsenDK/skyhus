import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The window waits for actions that stop or start a service (feature 0008).
UI.Sheet {
    id: sheet
    objectName: "closingSheet"

    required property var controller

    closePolicy: T.Popup.NoAutoClose
    visible: controller.closing && !warning.visible
    title: "Skyhus closes when the work is done"

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
        text: "The window closes by itself when the action is done."
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            objectName: "forceCloseButton"
            text: "Close anyway"
            onClicked: warning.open()
        }
    ]

    // The warning before the window closes during an action.
    UI.Sheet {
        id: warning
        objectName: "forceCloseWarning"

        closePolicy: T.Popup.NoAutoClose
        title: "Close anyway?"

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
                text: "The service can stay stopped if you close now. "
                      + "Start it again in the \"Service\" card the next time you open Skyhus."
                font: Theme.body
                color: Theme.textPrimary
            }
        }

        buttons: [
            UI.SecondaryButton {
                text: "Wait"
                onClicked: warning.close()
            },
            UI.SecondaryButton {
                objectName: "forceCloseConfirmButton"
                destructive: true
                text: "Close now"
                onClicked: sheet.controller.forceClose()
            }
        ]
    }
}
