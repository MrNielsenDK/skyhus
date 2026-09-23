import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus

// The primary button: filled with accent and text in onAccent.
T.Button {
    id: control

    property string iconName

    implicitWidth: Math.max(implicitBackgroundWidth, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Theme.controlHeight
    leftPadding: Theme.spacingM
    rightPadding: Theme.spacingM
    font: Theme.body
    opacity: enabled ? 1 : Theme.disabledOpacity

    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight

        RowLayout {
            id: content
            anchors.centerIn: parent
            width: Math.min(implicitWidth, parent.width)
            spacing: Theme.spacingXS

            Icon {
                visible: control.iconName !== ""
                name: control.iconName
                color: label.color
                size: Theme.iconMedium
            }
            Text {
                id: label
                text: control.text
                font: control.font
                color: Theme.onAccent
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
            }
        }
    }

    background: Rectangle {
        implicitWidth: Theme.controlHeight
        radius: Theme.radiusControl
        color: control.down ? Qt.darker(Theme.accent, 1.15) : Theme.accent

        Behavior on color {
            ColorAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
        }

        FocusRing {
            shown: control.visualFocus
        }
    }
}
