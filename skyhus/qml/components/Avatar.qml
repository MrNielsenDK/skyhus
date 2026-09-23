import QtQuick
import Skyhus

// A round avatar with the initials and the fixed color of the account.
Rectangle {
    id: avatar
    objectName: "avatar"

    property string initials
    property color textColor: Theme.onAccent
    property int size: Theme.avatarSmall

    implicitWidth: size
    implicitHeight: size
    radius: size / 2
    gradient: Gradient {
        GradientStop { position: 0; color: Qt.lighter(avatar.color, 1.12) }
        GradientStop { position: 1; color: avatar.color }
    }

    Text {
        anchors.centerIn: parent
        text: avatar.initials
        color: avatar.textColor
        font.family: Theme.headline.family
        font.weight: Font.DemiBold
        font.pixelSize: Math.round(avatar.size * Theme.avatarTextScale)
    }
}
