import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OneDriveGui
import "." as UI

// Kortet "Service": servicens tilstand, siden hvornår, den seneste fejllinje og en knap.
// Under kortet står en fejlbesked, hvis en handling fejlede, eller hvis status ikke kan læses.
// Under "Resynkroniserer" og "Resync er færdig" viser kortet fremdriften (feature 0009).
// Under "Resynkroniserer" har kortet knappen "Afbryd resync" (feature 0010).
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
    // Fremdriften fra AccountListModel.serviceProgress. Tom eller {"visible": false} uden resync.
    property var progress: ({})
    // Knappen "Afbryd resync" er synlig. AccountListModel.serviceCancellable.
    property bool cancellable: false
    readonly property bool progressVisible: progress !== undefined && progress !== null && progress.visible === true
    readonly property bool progressActive: progressVisible && progress.active === true

    signal actionClicked()
    signal cancelResyncClicked()

    function actionText(name) {
        switch (name) {
        case "restart": return "Genstart servicen"
        case "start": return "Start servicen"
        case "resync": return "Genstart med resync"
        default: return ""
        }
    }

    function actionDetail(name) {
        switch (name) {
        case "restart": return "Stop klienten, og start den igen."
        case "start": return "Nulstil fejlen, og start klienten."
        case "resync": return "Klienten sammenligner hele kontoen med OneDrive igen."
        default: return ""
        }
    }

    Layout.fillWidth: true
    spacing: Theme.spacingS

    UI.Card {
        title: "Service"

        UI.Row {
            first: true
            text: "Tilstand"
            detail: serviceCard.since !== "" ? "Siden " + serviceCard.since : ""

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

        // Fremdriften for --resync: fase, antal, bjælke, seneste fil og tid. Bagefter resultatet.
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

        // Den seneste fejllinje fra journalen. Brugeren kan markere og kopiere den.
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
            text: "Afbryd resync"
            detail: "Kontoen synkroniserer ikke, før du starter en ny resync."

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
                text: "Afbryd resync"
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
