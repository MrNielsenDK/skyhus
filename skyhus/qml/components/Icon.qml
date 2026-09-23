import QtQuick
import Skyhus

// A Lucide icon from assets/icons. The color follows the text next to the icon.
Image {
    id: icon

    property string name
    property color color: Theme.textPrimary
    property int size: Theme.iconMedium

    width: size
    height: size
    sourceSize.width: size
    sourceSize.height: size
    fillMode: Image.PreserveAspectFit
    source: name === "" ? "" : "image://icon/" + name + "/" + String(color).substring(1)
}
