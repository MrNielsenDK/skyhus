import QtQuick
import QtQuick.Templates as T
import Skyhus

// A switch as on iOS and macOS.
T.Switch {
    id: control

    implicitWidth: Theme.toggleWidth
    implicitHeight: Theme.toggleHeight
    padding: 0
    opacity: enabled ? 1 : Theme.disabledOpacity

    indicator: Rectangle {
        width: Theme.toggleWidth
        height: Theme.toggleHeight
        radius: height / 2
        color: control.checked ? Theme.accent : Theme.controlFill

        Behavior on color {
            ColorAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
        }

        Rectangle {
            width: parent.height - 2 * Theme.toggleInset
            height: width
            radius: width / 2
            y: Theme.toggleInset
            x: control.checked ? parent.width - width - Theme.toggleInset : Theme.toggleInset
            color: Theme.knob
            border.width: Theme.hairline
            border.color: Theme.separator

            Behavior on x {
                NumberAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
            }
        }

        FocusRing {
            shown: control.visualFocus
            baseRadius: parent.radius
        }
    }

    contentItem: Item {}
}
