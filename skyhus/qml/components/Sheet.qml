import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus

// A sheet that slides down from the top of the window. The rest of the window is dimmed.
T.Popup {
    id: sheet

    property string title
    property int preferredWidth: Theme.sheetWidth
    default property alias content: body.data
    property alias buttons: buttonRow.data

    parent: T.Overlay.overlay
    x: Math.round((parent.width - width) / 2)
    y: 0
    width: Math.min(parent.width - 2 * Theme.spacingXL, preferredWidth)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    padding: Theme.spacingXL
    modal: true
    dim: true
    closePolicy: T.Popup.CloseOnEscape

    enter: Transition {
        NumberAnimation {
            property: "y"
            from: -sheet.height
            to: 0
            duration: Theme.animSheet
            easing.type: Theme.animEasing
        }
    }
    exit: Transition {
        NumberAnimation {
            property: "y"
            from: 0
            to: -sheet.height
            duration: Theme.animSheet
            easing.type: Theme.animEasing
        }
    }

    T.Overlay.modal: Rectangle {
        color: Theme.scrim

        Behavior on opacity {
            NumberAnimation { duration: Theme.animSheet; easing.type: Theme.animEasing }
        }
    }

    background: Item {
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: -Theme.hairline
            anchors.rightMargin: -Theme.hairline
            anchors.bottomMargin: -Theme.spacingXS
            bottomLeftRadius: Theme.radiusCard + Theme.spacingXS
            bottomRightRadius: Theme.radiusCard + Theme.spacingXS
            color: Theme.shadow
            opacity: 0.5
        }
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: -Theme.hairline
            anchors.rightMargin: -Theme.hairline
            anchors.bottomMargin: -Theme.hairline
            bottomLeftRadius: Theme.radiusCard + Theme.hairline
            bottomRightRadius: Theme.radiusCard + Theme.hairline
            color: Theme.shadow
        }
        Rectangle {
            anchors.fill: parent
            bottomLeftRadius: Theme.radiusCard
            bottomRightRadius: Theme.radiusCard
            color: Theme.cardBg
        }
    }

    contentItem: ColumnLayout {
        spacing: Theme.spacingL

        Text {
            Layout.fillWidth: true
            visible: sheet.title !== ""
            text: sheet.title
            font: Theme.title
            color: Theme.textPrimary
            wrapMode: Text.Wrap
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacingM
        }

        RowLayout {
            id: buttonRow
            Layout.alignment: Qt.AlignRight
            spacing: Theme.spacingS
            visible: children.length > 0
        }
    }
}
