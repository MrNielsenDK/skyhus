import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OneDriveGui
import "." as UI

// Kortet "Service": servicens tilstand, siden hvornår, den seneste fejllinje og en knap.
// Under kortet står en fejlbesked, hvis en handling fejlede, eller hvis status ikke kan læses.
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

    signal actionClicked()

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
    }

    UI.InlineError {
        objectName: "serviceMessage"
        Layout.leftMargin: Theme.spacingXS
        text: serviceCard.message
    }
}
