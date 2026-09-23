import QtQuick
import QtQuick.Layouts
import OneDriveGui

// Banneret øverst i vinduet i sikker tilstand (feature 0007). Tonen er warning.
Rectangle {
    id: banner
    objectName: "safeModeBanner"

    readonly property string text: "Sikker tilstand – applikationen ændrer ikke noget på systemet"

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
