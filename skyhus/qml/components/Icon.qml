import QtQuick
import Skyhus

// Et Lucide-ikon fra assets/icons. Farven følger teksten ved siden af ikonet.
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
