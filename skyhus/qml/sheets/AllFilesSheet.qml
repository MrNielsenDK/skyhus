import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The sheet "All files" (feature 0019): the newest 200 files from the card "Activity".
UI.Sheet {
    id: sheet
    objectName: "allFilesSheet"

    required property var controller

    preferredWidth: Theme.sheetWideWidth
    height: Math.min(parent.height - Theme.spacingXL, implicitHeight)
    closePolicy: T.Popup.CloseOnEscape
    visible: controller.allFilesOpen
    title: "Files in the last 24 hours"
    onClosed: controller.closeAllFiles()

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: fileList.contentHeight
        radius: Theme.radiusCard
        color: Theme.windowBg
        border.width: Theme.hairline
        border.color: Theme.separator

        ListView {
            id: fileList
            objectName: "allFilesList"
            anchors.fill: parent
            anchors.margins: Theme.spacingS
            clip: true
            spacing: Theme.spacingXS
            boundsBehavior: Flickable.StopAtBounds
            model: sheet.controller.activityAllFiles
            ScrollBar.vertical: ScrollBar {}

            delegate: UI.FileEventRow {
                width: ListView.view.width
            }
        }
    }

    buttons: [
        UI.SecondaryButton {
            text: "Close"
            onClicked: sheet.controller.closeAllFiles()
        }
    ]
}
