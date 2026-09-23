import QtQuick
import Skyhus

// The ring around a focused item: 3 px in accent with 50 % opacity.
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
