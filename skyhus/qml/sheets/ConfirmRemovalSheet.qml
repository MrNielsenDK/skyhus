import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The confirmation of the local paths that the application moves to Trash.
UI.Sheet {
    id: sheet
    objectName: "confirmRemoval"

    required property var controller

    preferredWidth: Theme.sheetWideWidth
    height: Math.min(parent.height - Theme.spacingXL, implicitHeight)
    closePolicy: T.Popup.NoAutoClose
    visible: controller.pickerState === "confirm"
    title: "Remove local folders and files"

    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Skyhus moves these local folders and files to Trash. OneDrive keeps them."
        font: Theme.body
        color: Theme.textPrimary
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: removalList.contentHeight
        radius: Theme.radiusCard
        color: Theme.windowBg
        border.width: Theme.hairline
        border.color: Theme.separator

        ListView {
            id: removalList
            objectName: "removalList"
            anchors.fill: parent
            anchors.margins: Theme.hairline
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: sheet.controller.removalItems
            ScrollBar.vertical: ScrollBar {}

            delegate: Item {
                required property int index
                required property string modelData

                width: ListView.view.width
                height: Theme.treeRowHeight

                Rectangle {
                    visible: index > 0
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: Theme.spacingM
                    height: Theme.hairline
                    color: Theme.separator
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingM
                    anchors.rightMargin: Theme.spacingM
                    spacing: Theme.spacingS

                    UI.Icon {
                        name: "trash-2"
                        color: Theme.textSecondary
                    }
                    Text {
                        Layout.fillWidth: true
                        elide: Text.ElideMiddle
                        text: modelData
                        font: Theme.body
                        color: Theme.textPrimary
                    }
                }
            }
        }
    }

    Text {
        objectName: "removalSize"
        text: "Total size: " + sheet.controller.removalSize
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Cancel"
            onClicked: sheet.controller.cancelRemoval()
        },
        UI.SecondaryButton {
            destructive: true
            text: "Move to Trash"
            onClicked: sheet.controller.confirmRemoval()
        }
    ]
}
