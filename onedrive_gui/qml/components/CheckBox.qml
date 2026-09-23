import QtQuick
import QtQuick.Shapes
import QtQuick.Templates as T
import OneDriveGui

// Et afkrydsningsfelt på 14 px med afrundede hjørner. Fyldes med accent.
T.CheckBox {
    id: control

    readonly property bool filled: checkState !== Qt.Unchecked

    implicitWidth: implicitIndicatorWidth + (text !== "" ? spacing + implicitContentWidth : 0)
    implicitHeight: Math.max(implicitIndicatorHeight, implicitContentHeight)
    padding: 0
    spacing: Theme.spacingS
    font: Theme.body
    opacity: enabled ? 1 : Theme.disabledOpacity

    indicator: Rectangle {
        implicitWidth: Theme.checkBoxSize
        implicitHeight: Theme.checkBoxSize
        y: (control.height - height) / 2
        radius: Theme.radiusCheck
        color: control.filled ? Theme.accent : Theme.cardBg
        border.width: control.filled ? 0 : Theme.hairline
        border.color: Theme.controlBorder

        Behavior on color {
            ColorAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
        }

        // Fluebenet og stregen er tegnet som figurer. Et ikon med 1,5 px streg er for tyndt i 14 px.
        Shape {
            id: glyph
            anchors.fill: parent
            visible: control.filled
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeColor: Theme.onAccent
                strokeWidth: Theme.checkStroke
                fillColor: Theme.transparent
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                startX: control.checkState === Qt.Checked ? glyph.width * 0.26 : glyph.width * 0.28
                startY: control.checkState === Qt.Checked ? glyph.height * 0.52 : glyph.height * 0.5

                PathLine {
                    x: control.checkState === Qt.Checked ? glyph.width * 0.43 : glyph.width * 0.5
                    y: control.checkState === Qt.Checked ? glyph.height * 0.69 : glyph.height * 0.5
                }
                PathLine {
                    x: control.checkState === Qt.Checked ? glyph.width * 0.75 : glyph.width * 0.72
                    y: control.checkState === Qt.Checked ? glyph.height * 0.33 : glyph.height * 0.5
                }
            }
        }

        FocusRing {
            shown: control.visualFocus
            baseRadius: Theme.radiusCheck
        }
    }

    contentItem: Text {
        leftPadding: control.text !== "" ? control.indicator.width + control.spacing : 0
        visible: control.text !== ""
        text: control.text
        font: control.font
        color: Theme.textPrimary
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
