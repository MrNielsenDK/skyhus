import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import OneDriveGui
import "../components" as UI

// Bekræftelsen af de lokale stier, som applikationen flytter til papirkurven.
UI.Sheet {
    id: sheet
    objectName: "confirmRemoval"

    required property var controller

    preferredWidth: Theme.sheetWideWidth
    height: Math.min(parent.height - Theme.spacingXL, implicitHeight)
    closePolicy: T.Popup.NoAutoClose
    visible: controller.pickerState === "confirm"
    title: "Fjern lokale mapper og filer"

    Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: "Applikationen flytter disse lokale mapper og filer til papirkurven. OneDrive beholder dem."
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
        text: "Samlet størrelse: " + sheet.controller.removalSize
        font: Theme.caption
        color: Theme.textSecondary
    }

    buttons: [
        UI.SecondaryButton {
            text: "Annullér"
            onClicked: sheet.controller.cancelRemoval()
        },
        UI.SecondaryButton {
            destructive: true
            text: "Flyt til papirkurven"
            onClicked: sheet.controller.confirmRemoval()
        }
    ]
}
