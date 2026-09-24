import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Skyhus

// The card "Activity" (feature 0019): the last 24 hours from the journal of the service.
// A summary, the problems grouped by kind, and the newest files.
Card {
    id: card
    objectName: "activityCard"

    required property var controller
    readonly property string mode: controller.activityState

    title: "Activity"

    // Summary and buttons
    Item {
        Layout.fillWidth: true
        implicitHeight: Math.max(Theme.rowHeight, summaryRow.implicitHeight + 2 * Theme.spacingS)

        RowLayout {
            id: summaryRow
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingM
            anchors.rightMargin: Theme.spacingM
            spacing: Theme.spacingS

            Text {
                objectName: "activitySummary"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: card.mode === "no_service" ? "No service. There is no activity to show."
                      : card.mode === "loading" ? "Reading the journal …"
                      : card.controller.activitySummary
                font: Theme.body
                color: Theme.textSecondary
            }
            BusyIndicator {
                visible: card.controller.activityLoading
                running: visible
                implicitWidth: Theme.iconMedium
                implicitHeight: Theme.iconMedium
                padding: 0
                palette.dark: Theme.textSecondary
            }
            SecondaryButton {
                objectName: "activityRefreshButton"
                visible: card.mode === "ready"
                enabled: !card.controller.activityLoading
                text: "Refresh"
                onClicked: card.controller.refreshActivity()
            }
            SecondaryButton {
                objectName: "copyProblemsButton"
                visible: card.mode === "ready"
                enabled: card.controller.activityProblems.length > 0
                text: "Copy problems"
                onClicked: card.controller.copyProblems()
            }
        }
    }

    // Problems
    Item {
        Layout.fillWidth: true
        visible: card.mode === "ready"
        implicitHeight: problemColumn.implicitHeight + 2 * Theme.spacingS

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.spacingM
            anchors.rightMargin: Theme.spacingM
            height: Theme.hairline
            color: Theme.separator
        }

        ColumnLayout {
            id: problemColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Theme.spacingM
            anchors.rightMargin: Theme.spacingM
            spacing: Theme.spacingS

            Text {
                objectName: "noProblemsText"
                Layout.fillWidth: true
                visible: card.controller.activityProblems.length === 0
                text: "No problems in the last 24 hours"
                font: Theme.body
                color: Theme.textSecondary
            }
            Repeater {
                model: card.controller.activityProblems

                RowLayout {
                    objectName: "problemRow"
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Theme.spacingS

                    StatusDot {
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: Theme.spacingXS
                        tone: modelData.tone
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Text {
                            objectName: "problemTitle"
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: modelData.title
                            font: Theme.body
                            color: modelData.tone === "danger" ? Theme.danger : Theme.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.detail
                            font: Theme.caption
                            color: Theme.textSecondary
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }
        }
    }

    // Recent files
    Item {
        Layout.fillWidth: true
        visible: card.mode === "ready" && card.controller.activityRecent.length > 0
        implicitHeight: filesColumn.implicitHeight + 2 * Theme.spacingS

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.spacingM
            anchors.rightMargin: Theme.spacingM
            height: Theme.hairline
            color: Theme.separator
        }

        ColumnLayout {
            id: filesColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Theme.spacingM
            anchors.rightMargin: Theme.spacingM
            spacing: Theme.spacingXS

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: "Recent files"
                    font: Theme.headline
                    color: Theme.textPrimary
                }
                SecondaryButton {
                    objectName: "showAllFilesButton"
                    text: "Show all"
                    onClicked: card.controller.showAllFiles()
                }
            }
            Repeater {
                model: card.controller.activityRecent

                FileEventRow {
                    objectName: "recentFileRow"
                    Layout.fillWidth: true
                }
            }
        }
    }
}
