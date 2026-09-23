import QtQuick
import Skyhus

// A status dot. tone is the name of a theme token: "success", "warning", "danger"
// or "textSecondary". Feature 0004 can set tone from the state of the service.
Rectangle {
    id: dot
    objectName: "statusDot"

    property string tone: "textSecondary"
    property bool outlined: false

    function toneColor(name) {
        switch (name) {
        case "success": return Theme.success
        case "warning": return Theme.warning
        case "danger": return Theme.danger
        default: return Theme.textSecondary
        }
    }

    implicitWidth: Theme.statusDot
    implicitHeight: Theme.statusDot
    radius: width / 2
    color: toneColor(tone)
    border.width: outlined ? Theme.hairline : 0
    border.color: Theme.onAccent

    Behavior on color {
        ColorAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
    }
}
