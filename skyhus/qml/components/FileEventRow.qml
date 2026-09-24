import QtQuick
import QtQuick.Layouts
import Skyhus

// 1 file in the card "Activity" and in the sheet "All files" (feature 0019): an icon for the direction, the path and the time.
RowLayout {
    id: row

    required property var modelData

    spacing: Theme.spacingS

    Icon {
        name: row.modelData.icon
        color: row.modelData.tone === "danger" ? Theme.danger : Theme.textSecondary
    }
    Text {
        Layout.fillWidth: true
        text: row.modelData.path
        font: Theme.body
        color: Theme.textPrimary
        elide: Text.ElideMiddle
    }
    Text {
        text: row.modelData.verb + " · " + row.modelData.when
        font: Theme.caption
        color: row.modelData.tone === "danger" ? Theme.danger : Theme.textSecondary
    }
}
