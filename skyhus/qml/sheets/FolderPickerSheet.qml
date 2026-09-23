import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The folder picker. The tree shows the folders on OneDrive with check boxes in 3 states.
UI.Sheet {
    id: sheet
    objectName: "folderPicker"

    required property var controller
    readonly property var visibleStates: ["loading", "open", "checking", "applying"]
    readonly property bool busy: controller.pickerState !== "open"

    preferredWidth: Theme.sheetWideWidth
    height: parent.height - Theme.spacingXL
    closePolicy: T.Popup.NoAutoClose
    visible: visibleStates.indexOf(controller.pickerState) >= 0
    title: "Choose folders: " + controller.pickerAccountName

    UI.Card {
        UI.Row {
            first: true
            text: "Sync all folders"

            UI.Toggle {
                objectName: "syncAllBox"
                checked: sheet.controller.syncAll
                enabled: !sheet.busy
                onToggled: sheet.controller.setSyncAll(checked)
            }
        }
        UI.Row {
            text: "Sync files in the root"

            UI.Toggle {
                objectName: "syncRootFilesBox"
                checked: sheet.controller.syncRootFiles
                enabled: !sheet.busy && !sheet.controller.syncAll
                onToggled: sheet.controller.setSyncRootFiles(checked)
            }
        }
    }

    RowLayout {
        objectName: "unknownRulesLabel"
        Layout.fillWidth: true
        visible: sheet.controller.pickerUnknownRules
        spacing: Theme.spacingS

        UI.Icon {
            Layout.alignment: Qt.AlignTop
            name: "triangle-alert"
            color: Theme.warning
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Theme.caption
            color: Theme.textSecondary
            text: sheet.controller.syncAll
                  ? "sync_list contains rules that the folder picker does not show. \"Sync all folders\" removes sync_list and also those rules."
                  : "sync_list contains rules that the folder picker does not show. Skyhus keeps them."
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        radius: Theme.radiusCard
        color: Theme.windowBg
        border.width: Theme.hairline
        border.color: Theme.separator

        ListView {
            id: tree
            objectName: "folderTree"
            anchors.fill: parent
            anchors.margins: Theme.hairline
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            enabled: !sheet.busy && !sheet.controller.syncAll
            opacity: enabled ? 1 : Theme.disabledOpacity
            model: sheet.controller.folders
            ScrollBar.vertical: ScrollBar {}

            delegate: Item {
                id: row

                required property int index
                required property string name
                required property string path
                required property int depth
                required property int checkState
                required property bool hasChildren
                required property bool expanded
                required property bool loading
                required property bool available

                width: ListView.view.width
                height: Theme.treeRowHeight

                Rectangle {
                    visible: row.index > 0
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: Theme.spacingM
                    height: Theme.hairline
                    color: Theme.separator
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingS + row.depth * Theme.treeIndent
                    anchors.rightMargin: Theme.spacingM
                    spacing: Theme.spacingS

                    T.AbstractButton {
                        id: disclosure
                        implicitWidth: Theme.iconMedium
                        implicitHeight: Theme.iconMedium
                        opacity: row.hasChildren ? 1 : 0
                        enabled: row.hasChildren
                        onClicked: sheet.controller.expandFolder(row.index)

                        contentItem: UI.Icon {
                            name: row.expanded ? "chevron-down" : "chevron-right"
                            color: Theme.textSecondary
                        }
                        background: UI.FocusRing {
                            shown: disclosure.visualFocus
                        }
                    }
                    UI.CheckBox {
                        tristate: true
                        checkState: row.checkState
                        enabled: row.available
                        // The controller decides the new state. The model sends it back.
                        nextCheckState: function() { return row.checkState }
                        onClicked: sheet.controller.toggleFolder(row.index)
                    }
                    UI.Icon {
                        name: "folder"
                        color: Theme.textSecondary
                    }
                    Text {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        font: Theme.body
                        color: row.available ? Theme.textPrimary : Theme.textSecondary
                        text: row.available ? row.name : row.name + " (not available, listed in skip_dir)"
                    }
                    BusyIndicator {
                        Layout.preferredWidth: Theme.iconMedium
                        Layout.preferredHeight: Theme.iconMedium
                        visible: row.loading
                        running: row.loading
                        palette.dark: Theme.textSecondary
                    }
                }
            }
        }
    }

    // During a change of an account that has synced before, ApplyProgressSheet shows the steps instead.
    RowLayout {
        Layout.fillWidth: true
        visible: sheet.busy && sheet.controller.applyState === ""
        spacing: Theme.spacingS

        BusyIndicator {
            Layout.preferredWidth: Theme.controlHeight
            Layout.preferredHeight: Theme.controlHeight
            running: parent.visible
            palette.dark: Theme.textSecondary
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Theme.body
            color: Theme.textSecondary
            text: {
                switch (sheet.controller.pickerState) {
                case "loading": return "Getting the folders from OneDrive …"
                case "checking": return "Finding the local folders that go away …"
                case "applying": return "Uploading local changes and saving the selection. This can take a long time."
                default: return ""
                }
            }
        }
    }

    UI.InlineError {
        objectName: "pickerError"
        text: sheet.controller.pickerError
    }

    buttons: [
        UI.SecondaryButton {
            text: "Cancel"
            enabled: sheet.controller.pickerState === "open" || sheet.controller.pickerState === "loading"
            onClicked: sheet.controller.closePicker()
        },
        UI.PrimaryButton {
            text: "OK"
            enabled: sheet.controller.pickerState === "open"
            onClicked: sheet.controller.acceptPicker()
        }
    ]
}
