import QtQuick
import QtQuick.Layouts
import Skyhus

// The banner at the top of the window in safe mode (feature 0007). The tone is warning.
Rectangle {
    id: banner
    objectName: "safeModeBanner"

    readonly property string text: "Safe mode – Skyhus does not change anything on the system"

    implicitHeight: row.implicitHeight + 2 * Theme.spacingS
    color: Qt.rgba(Theme.warning.r, Theme.warning.g, Theme.warning.b, 0.14)

    RowLayout {
        id: row
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Theme.spacingL
        anchors.rightMargin: Theme.spacingL
        spacing: Theme.spacingS

        Icon {
            Layout.alignment: Qt.AlignVCenter
            name: "triangle-alert"
            color: Theme.warning
        }
        Text {
            objectName: "safeModeText"
            Layout.fillWidth: true
            text: banner.text
            font: Theme.headline
            color: Theme.textPrimary
            wrapMode: Text.Wrap
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Theme.hairline
        color: Theme.separator
    }
}
