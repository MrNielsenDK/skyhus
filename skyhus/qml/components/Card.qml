import QtQuick
import QtQuick.Layouts
import Skyhus

// Et kort med afrundede hjørner. Rækkerne står under hinanden, og title står over kortet.
ColumnLayout {
    id: card

    property string title
    default property alias rows: body.data

    Layout.fillWidth: true
    spacing: Theme.spacingS

    Text {
        visible: card.title !== ""
        text: card.title
        font: Theme.headline
        color: Theme.textPrimary
        leftPadding: Theme.spacingXS
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: body.implicitHeight
        radius: Theme.radiusCard
        color: Theme.cardBg
        border.width: Theme.hairline
        border.color: Theme.separator

        ColumnLayout {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 0
        }
    }
}
