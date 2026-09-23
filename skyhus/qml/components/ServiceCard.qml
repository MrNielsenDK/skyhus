import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Skyhus
import "." as UI

// The "Service" card: the state of the service, since when, the latest error line and a button.
// Below the card is an error message if an action failed or if the status cannot be read.
// During "Resyncing" and "Resync complete", the card shows the progress (feature 0009).
// During "Resyncing", the card has the "Stop resync" button (feature 0010).
ColumnLayout {
    id: serviceCard
    objectName: "serviceCard"

    property string stateLabel
    property string tone: "textSecondary"
    property string since
    property string errorLine
    property string action
    property string actionLabel
    property bool busy: false
    property string message
    // The progress from AccountListModel.serviceProgress. Empty or {"visible": false} without resync.
    property var progress: ({})
    // The "Stop resync" button is visible. AccountListModel.serviceCancellable.
    property bool cancellable: false
    readonly property bool progressVisible: progress !== undefined && progress !== null && progress.visible === true
    readonly property bool progressActive: progressVisible && progress.active === true

    signal actionClicked()
    signal cancelResyncClicked()

    function actionText(name) {
        switch (name) {
        case "restart": return "Restart the service"
        case "start": return "Start the service"
        case "resync": return "Restart with resync"
        default: return ""
        }
    }

    function actionDetail(name) {
        switch (name) {
        case "restart": return "Stop the client and start it again."
        case "start": return "Reset the error and start the client."
        case "resync": return "The client compares all of the account with OneDrive again."
        default: return ""
        }
    }

    Layout.fillWidth: true
    spacing: Theme.spacingS

    UI.Card {
        title: "Service"

        UI.Row {
            first: true
            text: "State"
            detail: serviceCard.since !== "" ? "Since " + serviceCard.since : ""

            UI.StatusDot {
                tone: serviceCard.tone
            }
            Text {
                objectName: "serviceStateLabel"
                text: serviceCard.stateLabel
                font: Theme.body
                color: Theme.textSecondary
            }
        }

        // The progress of --resync: phase, count, bar, latest file and time. After that, the result.
        Item {
            objectName: "serviceProgressRow"
            Layout.fillWidth: true
            visible: serviceCard.progressVisible
            implicitHeight: progressContent.implicitHeight + 2 * Theme.spacingM

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                height: Theme.hairline
                color: Theme.separator
            }

            ColumnLayout {
                id: progressContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                spacing: Theme.spacingXS

                RowLayout {
                    Layout.fillWidth: true
                    visible: serviceCard.progressActive
                    spacing: Theme.spacingS

                    Text {
                        objectName: "serviceProgressPhase"
                        Layout.fillWidth: true
                        text: serviceCard.progressVisible ? serviceCard.progress.phase : ""
                        font: Theme.body
                        color: Theme.textPrimary
                        elide: Text.ElideRight
                    }
                    Text {
                        objectName: "serviceProgressCounter"
                        text: serviceCard.progressVisible ? serviceCard.progress.counter : ""
                        font: Theme.body
                        color: Theme.textSecondary
                    }
                }
                UI.ProgressBar {
                    objectName: "serviceProgressBar"
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.spacingXS
                    Layout.bottomMargin: Theme.spacingXS
                    visible: serviceCard.progressActive
                    indeterminate: serviceCard.progressVisible && !serviceCard.progress.determinate
                    value: serviceCard.progressVisible ? serviceCard.progress.value : 0
                }
                Text {
                    objectName: "serviceProgressLatest"
                    Layout.fillWidth: true
                    visible: serviceCard.progressActive && text !== ""
                    text: serviceCard.progressVisible ? serviceCard.progress.latest : ""
                    font: Theme.caption
                    color: Theme.textSecondary
                    elide: Text.ElideMiddle
                }
                Text {
                    objectName: "serviceProgressElapsed"
                    Layout.fillWidth: true
                    visible: serviceCard.progressActive && text !== ""
                    text: serviceCard.progressVisible ? serviceCard.progress.elapsed : ""
                    font: Theme.caption
                    color: Theme.textSecondary
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: serviceCard.progressVisible && serviceCard.progress.result !== ""
                    spacing: Theme.spacingS

                    UI.StatusDot {
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: Theme.spacingXS + Theme.hairline
                        tone: serviceCard.progressVisible && serviceCard.progress.result === "complete"
                              ? "success" : "warning"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Text {
                            objectName: "serviceProgressResult"
                            Layout.fillWidth: true
                            text: serviceCard.progressVisible ? serviceCard.progress.resultText : ""
                            font: Theme.body
                            color: Theme.textPrimary
                            elide: Text.ElideRight
                        }
                        Text {
                            objectName: "serviceProgressResultDetail"
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: serviceCard.progressVisible ? serviceCard.progress.resultDetail : ""
                            font: Theme.caption
                            color: Theme.textSecondary
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }

        // The latest error line from the journal. The user can select and copy it.
        Item {
            objectName: "serviceErrorRow"
            Layout.fillWidth: true
            visible: serviceCard.errorLine !== ""
            implicitHeight: errorContent.implicitHeight + 2 * Theme.spacingM

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                height: Theme.hairline
                color: Theme.separator
            }

            RowLayout {
                id: errorContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                spacing: Theme.spacingS

                UI.Icon {
                    Layout.alignment: Qt.AlignTop
                    name: "circle-alert"
                    color: Theme.danger
                }
                TextEdit {
                    objectName: "serviceErrorLine"
                    Layout.fillWidth: true
                    text: serviceCard.errorLine
                    readOnly: true
                    selectByMouse: true
                    selectByKeyboard: true
                    wrapMode: TextEdit.Wrap
                    font: Theme.body
                    color: Theme.textPrimary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                }
            }
        }

        UI.Row {
            objectName: "serviceActionRow"
            visible: serviceCard.actionLabel !== ""
            text: serviceCard.actionText(serviceCard.action)
            detail: serviceCard.actionDetail(serviceCard.action)

            BusyIndicator {
                objectName: "serviceSpinner"
                visible: serviceCard.busy
                running: serviceCard.busy
                padding: 0
                implicitWidth: Theme.controlHeight - Theme.spacingS
                implicitHeight: Theme.controlHeight - Theme.spacingS
                palette.dark: Theme.textSecondary
            }
            UI.SecondaryButton {
                objectName: "serviceActionButton"
                text: serviceCard.actionLabel
                enabled: !serviceCard.busy
                onClicked: serviceCard.actionClicked()
            }
        }

        UI.Row {
            objectName: "serviceCancelResyncRow"
            visible: serviceCard.cancellable
            text: "Stop resync"
            detail: "The account does not sync until you start a new resync."

            BusyIndicator {
                visible: serviceCard.busy
                running: serviceCard.busy
                padding: 0
                implicitWidth: Theme.controlHeight - Theme.spacingS
                implicitHeight: Theme.controlHeight - Theme.spacingS
                palette.dark: Theme.textSecondary
            }
            UI.SecondaryButton {
                objectName: "serviceCancelResyncButton"
                visible: serviceCard.cancellable
                text: "Stop resync"
                enabled: !serviceCard.busy
                onClicked: serviceCard.cancelResyncClicked()
            }
        }
    }

    UI.InlineError {
        objectName: "serviceMessage"
        Layout.leftMargin: Theme.spacingXS
        text: serviceCard.message
    }
}
