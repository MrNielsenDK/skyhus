import QtQuick
import QtQuick.Templates as T
import Skyhus

// A text field with a thin border and a focus ring.
T.TextField {
    id: control

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            placeholder.implicitWidth + leftPadding + rightPadding)
    implicitHeight: Theme.controlHeight
    leftPadding: Theme.spacingS
    rightPadding: Theme.spacingS
    verticalAlignment: TextInput.AlignVCenter
    font: Theme.body
    color: Theme.textPrimary
    selectionColor: Theme.accent
    selectedTextColor: Theme.onAccent
    placeholderTextColor: Theme.textSecondary
    opacity: enabled ? 1 : Theme.disabledOpacity

    Text {
        id: placeholder
        x: control.leftPadding
        y: control.topPadding
        width: control.width - control.leftPadding - control.rightPadding
        height: control.height - control.topPadding - control.bottomPadding
        text: control.placeholderText
        font: control.font
        color: control.placeholderTextColor
        verticalAlignment: control.verticalAlignment
        elide: Text.ElideRight
        visible: control.length === 0 && control.preeditText === ""
    }

    background: Rectangle {
        implicitWidth: Theme.fieldWidth
        radius: Theme.radiusControl
        color: Theme.cardBg
        border.width: Theme.hairline
        border.color: Theme.controlBorder

        FocusRing {
            shown: control.activeFocus
        }
    }
}
