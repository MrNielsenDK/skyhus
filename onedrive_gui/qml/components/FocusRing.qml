import QtQuick
import OneDriveGui

// Ringen om et fokuseret element: 3 px i accent med 50 % gennemsigtighed.
Rectangle {
    property bool shown: false
    property real baseRadius: Theme.radiusControl

    anchors.fill: parent
    anchors.margins: -Theme.focusRing
    radius: baseRadius + Theme.focusRing
    color: Theme.transparent
    border.width: Theme.focusRing
    border.color: Theme.focusRingColor
    visible: shown
}
