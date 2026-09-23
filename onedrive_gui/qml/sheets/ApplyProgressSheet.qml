import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import OneDriveGui
import "../components" as UI

// Arket "Ændrer mappevalg" med de 5 trin (feature 0009). Det erstatter spinneren i mappevælgeren.
// Arket lukker, når trin 5 er færdigt. Fejler et trin, bliver arket stående, til brugeren klikker "Luk".
// Under trin 2 kan brugeren klikke "Afbryd" (feature 0010). Så bliver arket stående med en besked.
UI.Sheet {
    id: sheet
    objectName: "applyProgressSheet"

    required property var controller
    readonly property bool failed: controller.applyState === "failed"
    readonly property bool cancelled: controller.applyState === "cancelled"

    closePolicy: T.Popup.NoAutoClose
    visible: controller.applyState !== ""
    title: "Ændrer mappevalg"

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

                    // Tilstanden som et tegn: prik, spinner eller advarsel.
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
        text: "Uploaden og resync kan tage lang tid for en stor konto."
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
            text: "Ændringen er afbrudt. Mappevalget er uændret."
            font: Theme.body
            color: Theme.textPrimary
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "Filer, som klienten nåede at uploade, bliver på OneDrive."
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
            text: sheet.controller.applyCancelling ? "Afbryder …" : "Afbryd"
            onClicked: sheet.controller.cancelApply()
        },
        UI.SecondaryButton {
            objectName: "applyProgressCloseButton"
            visible: sheet.failed || sheet.cancelled
            text: "Luk"
            onClicked: sheet.controller.closeApplyProgress()
        }
    ]
}
