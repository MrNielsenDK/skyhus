import QtQuick
import OneDriveGui

// En statusprik. tone er navnet på et tema-token: "success", "warning", "danger"
// eller "textSecondary". Feature 0004 kan sætte tone ud fra servicens tilstand.
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
