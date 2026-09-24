import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The sheet "Remove account?" (feature 0018).
// "loading": Skyhus reads what belongs to the account. "confirm": the user sees what Skyhus removes and keeps.
// "running": the steps with their state. During the upload, the user can click "Stop".
// "failed" and "cancelled": the sheet stays open until the user clicks "Close".
UI.Sheet {
    id: sheet
    objectName: "removeAccountSheet"

    required property var controller
    readonly property string mode: controller.removeState
    readonly property var plan: controller.removePlan
    readonly property bool confirming: mode === "confirm"
    readonly property bool working: mode === "running" || mode === "cancelled"
                                    || (mode === "failed" && controller.removeSteps.length > 0)

    preferredWidth: Theme.sheetWideWidth
    height: Math.min(parent.height - Theme.spacingXL, implicitHeight)
    closePolicy: T.Popup.NoAutoClose
    visible: mode !== ""
    title: sheet.confirming || mode === "loading" ? "Remove account?"
                                                  : "Removing the account " + (sheet.plan.name || "")

    // Loading
    RowLayout {
        Layout.fillWidth: true
        visible: sheet.mode === "loading"
        spacing: Theme.spacingS

        BusyIndicator {
            implicitWidth: Theme.iconMedium
            implicitHeight: Theme.iconMedium
            padding: 0
            running: parent.visible && sheet.visible
            palette.dark: Theme.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: "Checking the account …"
            font: Theme.body
            color: Theme.textSecondary
        }
    }

    // Confirmation
    Flickable {
        id: confirmFlick
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: confirmColumn.implicitHeight
        visible: sheet.confirming
        clip: true
        contentHeight: confirmColumn.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: confirmColumn
            width: confirmFlick.width
            spacing: Theme.spacingM

            Text {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: (sheet.plan.name || "") + " · " + (sheet.plan.confdir || "")
                font: Theme.body
                color: Theme.textPrimary
            }

            UI.Card {
                title: "Sync folder"

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.spacingM
                    spacing: Theme.spacingS

                    UI.CheckBox {
                        objectName: "removeSyncFolderBox"
                        Layout.fillWidth: true
                        visible: sheet.plan.syncTrashable === true
                        text: "Also move the local folder to the Trash"
                        checked: sheet.controller.removeSyncFolder
                        onToggled: sheet.controller.setRemoveSyncFolder(checked)
                    }
                    Text {
                        Layout.fillWidth: true
                        text: sheet.plan.syncPath || ""
                        font: Theme.caption
                        color: Theme.textSecondary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        objectName: "removeSyncReason"
                        Layout.fillWidth: true
                        visible: sheet.plan.syncTrashable === false
                        wrapMode: Text.Wrap
                        text: (sheet.plan.syncReason || "") + " The folder stays."
                        font: Theme.body
                        color: Theme.textPrimary
                    }
                    Text {
                        objectName: "localOnlyText"
                        Layout.fillWidth: true
                        visible: (sheet.plan.localOnlyText || "") !== ""
                        wrapMode: Text.Wrap
                        text: sheet.plan.localOnlyText || ""
                        font: Theme.body
                        color: sheet.controller.removeSyncFolder ? Theme.danger : Theme.textPrimary
                    }
                    Repeater {
                        model: sheet.plan.localOnlyPaths || []

                        Text {
                            required property string modelData
                            Layout.fillWidth: true
                            text: modelData
                            font: Theme.caption
                            color: Theme.textSecondary
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Skyhus removes"
                font: Theme.headline
                color: Theme.textPrimary
            }
            Repeater {
                objectName: "removeList"
                model: sheet.plan.removes || []

                Text {
                    required property string modelData
                    objectName: "removeLine"
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: "• " + modelData
                    font: Theme.body
                    color: Theme.textPrimary
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Skyhus does not remove"
                font: Theme.headline
                color: Theme.textPrimary
            }
            Repeater {
                model: sheet.plan.keeps || []

                Text {
                    required property string modelData
                    objectName: "keepLine"
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: "• " + modelData
                    font: Theme.body
                    color: Theme.textPrimary
                }
            }

            Text {
                objectName: "microsoftNote"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Microsoft still lists the OneDrive client as an app with access to the account. "
                      + "You can remove this access in the settings of your Microsoft account."
                font: Theme.caption
                color: Theme.textSecondary
            }
        }
    }

    // Progress
    UI.StepList {
        visible: sheet.working
        steps: sheet.controller.removeSteps
        rowName: "removeStepRow"
        stateName: "removeStepState"
        barName: "removeStepBar"
    }

    Text {
        objectName: "removeCancelledText"
        Layout.fillWidth: true
        visible: sheet.mode === "cancelled"
        wrapMode: Text.Wrap
        text: "The removal is stopped. The account did not change."
        font: Theme.body
        color: Theme.textPrimary
    }

    UI.InlineError {
        objectName: "removeError"
        text: sheet.mode === "failed" ? sheet.controller.removeError : ""
    }

    buttons: [
        UI.SecondaryButton {
            objectName: "removeCancelButton"
            visible: sheet.confirming
            text: "Cancel"
            onClicked: sheet.controller.closeRemoveAccount()
        },
        UI.SecondaryButton {
            objectName: "removeConfirmButton"
            visible: sheet.confirming
            destructive: true
            text: "Remove account"
            onClicked: sheet.controller.confirmRemoveAccount()
        },
        UI.SecondaryButton {
            objectName: "removeStopButton"
            visible: sheet.controller.removeCancellable || sheet.controller.removeCancelling
            enabled: !sheet.controller.removeCancelling
            text: sheet.controller.removeCancelling ? "Stopping …" : "Stop"
            onClicked: sheet.controller.stopRemoveAccount()
        },
        UI.SecondaryButton {
            objectName: "removeCloseButton"
            visible: sheet.mode === "failed" || sheet.mode === "cancelled"
            text: "Close"
            onClicked: sheet.controller.closeRemoveAccount()
        }
    ]
}
