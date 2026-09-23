import QtQuick
import QtQuick.Layouts
import Skyhus

// An error message with an icon in danger. The text is in textPrimary.
RowLayout {
    id: error

    property string text

    Layout.fillWidth: true
    visible: text !== ""
    spacing: Theme.spacingS

    Icon {
        Layout.alignment: Qt.AlignTop
        name: "circle-alert"
        color: Theme.danger
    }
    Text {
        Layout.fillWidth: true
        text: error.text
        font: Theme.body
        color: Theme.textPrimary
        wrapMode: Text.Wrap
    }
}
