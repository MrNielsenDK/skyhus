import QtQuick
import Skyhus

// A progress bar (feature 0009). value goes from 0 to 1.
// If indeterminate is set, the application does not know the total. Then a segment slides back and forth.
Item {
    id: bar
    objectName: "progressBar"

    property real value: 0
    property bool indeterminate: false

    implicitHeight: Theme.progressHeight
    implicitWidth: Theme.fieldWidth

    Accessible.role: Accessible.ProgressBar
    Accessible.name: indeterminate ? "Running" : Math.round(value * 100) + " %"

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: Theme.controlFill
        clip: true

        Rectangle {
            id: fill
            visible: !bar.indeterminate
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            width: Math.max(bar.value > 0 ? height : 0, parent.width * Math.min(1, Math.max(0, bar.value)))
            radius: height / 2
            color: Theme.accent

            Behavior on width {
                NumberAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
            }
        }

        Rectangle {
            id: slider
            visible: bar.indeterminate
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width / 3
            radius: height / 2
            color: Theme.accent

            SequentialAnimation on x {
                running: bar.indeterminate && bar.visible
                loops: Animation.Infinite
                NumberAnimation {
                    from: 0
                    to: track.width - slider.width
                    duration: Theme.animIndeterminate
                    easing.type: Easing.InOutQuad
                }
                NumberAnimation {
                    from: track.width - slider.width
                    to: 0
                    duration: Theme.animIndeterminate
                    easing.type: Easing.InOutQuad
                }
            }
        }
    }
}
