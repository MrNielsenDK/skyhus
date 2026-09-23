import QtQuick
import QtQuick.Layouts
import OneDriveGui

// En fejlbesked med et ikon i danger. Teksten står i textPrimary.
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
