import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Skyhus

// A card with the steps of a long action and the state of each step (feature 0009, feature 0018).
// Each step is a map from viewmodels.py: title, state, stateText, detail, latest, showBar, determinate, value.
Card {
    id: list

    required property var steps
    property string rowName: "stepRow"
    property string stateName: "stepState"
    property string barName: "stepBar"

    Repeater {
        model: list.steps

        delegate: Item {
            id: stepRow
            objectName: list.rowName

            required property int index
            required property var modelData

            Layout.fillWidth: true
            implicitHeight: Math.max(Theme.rowHeight, content.implicitHeight + 2 * Theme.spacingS)

            Rectangle {
                visible: stepRow.index > 0
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
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                spacing: Theme.spacingM

                // The state as a sign: dot, spinner or warning.
                Item {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: Theme.hairline
                    implicitWidth: Theme.iconMedium
                    implicitHeight: Theme.iconMedium

                    StatusDot {
                        anchors.centerIn: parent
                        visible: stepRow.modelData.state === "waiting" || stepRow.modelData.state === "done"
                                 || stepRow.modelData.state === "cancelled"
                        tone: stepRow.modelData.state === "done" ? "success"
                              : stepRow.modelData.state === "cancelled" ? "warning" : "textSecondary"
                        opacity: stepRow.modelData.state === "waiting" ? Theme.disabledOpacity : 1
                    }
                    BusyIndicator {
                        anchors.fill: parent
                        visible: stepRow.modelData.state === "running"
                        running: visible && list.visible
                        padding: 0
                        palette.dark: Theme.textSecondary
                    }
                    Icon {
                        anchors.centerIn: parent
                        visible: stepRow.modelData.state === "failed"
                        name: "circle-alert"
                        color: Theme.danger
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingXS

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingS

                        Text {
                            Layout.fillWidth: true
                            text: stepRow.modelData.title
                            font: Theme.body
                            color: stepRow.modelData.state === "waiting" ? Theme.textSecondary : Theme.textPrimary
                            elide: Text.ElideRight
                        }
                        Text {
                            objectName: list.stateName
                            text: stepRow.modelData.detail !== "" ? stepRow.modelData.detail
                                                                 : stepRow.modelData.stateText
                            font: Theme.caption
                            color: stepRow.modelData.state === "failed" ? Theme.danger : Theme.textSecondary
                        }
                    }
                    ProgressBar {
                        objectName: list.barName
                        Layout.fillWidth: true
                        visible: stepRow.modelData.showBar
                        indeterminate: !stepRow.modelData.determinate
                        value: stepRow.modelData.value
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: stepRow.modelData.latest !== "" && stepRow.modelData.state === "running"
                        text: stepRow.modelData.latest
                        font: Theme.caption
                        color: Theme.textSecondary
                        elide: Text.ElideMiddle
                    }
                }
            }
        }
    }
}
