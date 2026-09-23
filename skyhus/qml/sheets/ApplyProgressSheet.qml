import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The "Changing folder selection" sheet with the 5 steps (feature 0009). It replaces the spinner in the folder picker.
// The sheet closes when step 5 is done. If a step fails, the sheet stays open until the user clicks "Close".
// During step 2, the user can click "Stop" (feature 0010). Then the sheet stays open with a message.
UI.Sheet {
    id: sheet
    objectName: "applyProgressSheet"

    required property var controller
    readonly property bool failed: controller.applyState === "failed"
    readonly property bool cancelled: controller.applyState === "cancelled"

    closePolicy: T.Popup.NoAutoClose
    visible: controller.applyState !== ""
    title: "Changing folder selection"

    UI.Card {
        Repeater {
            model: sheet.controller.applySteps

            delegate: Item {
                id: stepRow
                objectName: "applyStepRow"

                required property int index
                required property var modelData

                Layout.fillWidth: true
                implicitHeight: Math.max(Theme.rowHeight, content.implicitHeight + 2 * Theme.spacingS)

                Rectangle {
                    visible: stepRow.index > 0
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: Theme.spacingM
                    anchors.rightMargin: Theme.spacingM
                    height: Theme.hairline
                    color: Theme.separator
                }

                RowLayout {
                    id: content
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Theme.spacingM
                    anchors.rightMargin: Theme.spacingM
                    spacing: Theme.spacingM

                    // The state as a sign: dot, spinner or warning.
                    Item {
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: Theme.hairline
                        implicitWidth: Theme.iconMedium
                        implicitHeight: Theme.iconMedium

                        UI.StatusDot {
                            anchors.centerIn: parent
                            visible: stepRow.modelData.state === "waiting" || stepRow.modelData.state === "done"
                                     || stepRow.modelData.state === "cancelled"
                            tone: stepRow.modelData.state === "done" ? "success"
                                  : stepRow.modelData.state === "cancelled" ? "warning" : "textSecondary"
                            opacity: stepRow.modelData.state === "waiting" ? Theme.disabledOpacity : 1
                        }
                        BusyIndicator {
                            anchors.fill: parent
                            visible: stepRow.modelData.state === "running"
                            running: visible && sheet.visible
                            padding: 0
                            palette.dark: Theme.textSecondary
                        }
                        UI.Icon {
                            anchors.centerIn: parent
                            visible: stepRow.modelData.state === "failed"
                            name: "circle-alert"
                            color: Theme.danger
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingXS

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spacingS

                            Text {
                                Layout.fillWidth: true
                                text: stepRow.modelData.title
                                font: Theme.body
                                color: stepRow.modelData.state === "waiting" ? Theme.textSecondary : Theme.textPrimary
                                elide: Text.ElideRight
                            }
                            Text {
                                objectName: "applyStepState"
                                text: stepRow.modelData.detail !== "" ? stepRow.modelData.detail
                                                                     : stepRow.modelData.stateText
                                font: Theme.caption
                                color: stepRow.modelData.state === "failed" ? Theme.danger : Theme.textSecondary
                            }
                        }
                        UI.ProgressBar {
                            objectName: "applyStepBar"
                            Layout.fillWidth: true
                            visible: stepRow.modelData.showBar
                            indeterminate: !stepRow.modelData.determinate
                            value: stepRow.modelData.value
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: stepRow.modelData.latest !== "" && stepRow.modelData.state === "running"
                            text: stepRow.modelData.latest
                            font: Theme.caption
                            color: Theme.textSecondary
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        visible: !sheet.failed && !sheet.cancelled
        wrapMode: Text.Wrap
        text: "The upload and the resync can take a long time for a large account."
        font: Theme.caption
        color: Theme.textSecondary
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: sheet.cancelled
        spacing: Theme.spacingXS

        Text {
            objectName: "applyCancelledText"
            Layout.fillWidth: true
            visible: sheet.cancelled
            wrapMode: Text.Wrap
            text: "The change is stopped. The folder selection did not change."
            font: Theme.body
            color: Theme.textPrimary
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "Files that the client uploaded before the stop stay on OneDrive."
            font: Theme.caption
            color: Theme.textSecondary
        }
    }

    UI.InlineError {
        objectName: "applyProgressError"
        text: sheet.failed ? sheet.controller.pickerError : ""
    }

    buttons: [
        UI.SecondaryButton {
            objectName: "applyCancelButton"
            visible: sheet.controller.applyCancellable || sheet.controller.applyCancelling
            enabled: !sheet.controller.applyCancelling
            text: sheet.controller.applyCancelling ? "Stopping …" : "Stop"
            onClicked: sheet.controller.cancelApply()
        },
        UI.SecondaryButton {
            objectName: "applyProgressCloseButton"
            visible: sheet.failed || sheet.cancelled
            text: "Close"
            onClicked: sheet.controller.closeApplyProgress()
        }
    ]
}
