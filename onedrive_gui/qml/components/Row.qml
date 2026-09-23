import QtQuick
import QtQuick.Layouts
import OneDriveGui

// En række i et kort: tekst til venstre, værdi eller knap til højre.
// En tynd streg adskiller rækken fra rækken over den, undtagen når first er sat.
Item {
    id: row

    property string text
    property string detail
    property string value
    property bool first: false
    default property alias trailing: trailingRow.data

    Layout.fillWidth: true
    implicitHeight: Math.max(Theme.rowHeight, content.implicitHeight + 2 * Theme.spacingS)

    Rectangle {
        visible: !row.first
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
        anchors.fill: parent
        anchors.leftMargin: Theme.spacingM
        anchors.rightMargin: Theme.spacingM
        spacing: Theme.spacingM

        ColumnLayout {
            Layout.fillWidth: row.value === ""
            Layout.alignment: Qt.AlignVCenter
            spacing: 0

            Text {
                Layout.fillWidth: true
                text: row.text
                font: Theme.body
                color: Theme.textPrimary
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: row.detail !== ""
                text: row.detail
                font: Theme.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            visible: row.value !== ""
            text: row.value
            font: Theme.body
            color: Theme.textSecondary
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideMiddle
        }

        RowLayout {
            id: trailingRow
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.spacingS
            visible: children.length > 0
        }
    }
}
