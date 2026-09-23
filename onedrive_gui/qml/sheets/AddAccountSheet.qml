import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import OneDriveGui
import "../components" as UI

UI.Sheet {
    id: sheet

    required property var controller
    property bool syncDirEdited: false

    title: "Tilføj konto"

    onAboutToShow: {
        nameField.text = ""
        syncField.text = ""
        errorLabel.text = ""
        syncDirEdited = false
    }
    onOpened: nameField.forceActiveFocus()

    function submit() {
        var error = controller.addAccount(nameField.text, syncField.text)
        if (error !== "")
            errorLabel.text = error
        else
            sheet.close()
    }

    Text {
        text: "Visningsnavn"
        font: Theme.headline
        color: Theme.textPrimary
    }
    UI.TextField {
        id: nameField
        Layout.fillWidth: true
        placeholderText: "Fx Firma 2"
        onTextChanged: {
            if (!sheet.syncDirEdited)
                syncField.text = sheet.controller.suggestSyncDir(text)
        }
        onAccepted: sheet.submit()
    }

    Text {
        Layout.topMargin: Theme.spacingS
        text: "Synkmappe"
        font: Theme.headline
        color: Theme.textPrimary
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingS

        UI.TextField {
            id: syncField
            Layout.fillWidth: true
            onTextEdited: sheet.syncDirEdited = true
            onAccepted: sheet.submit()
        }
        UI.SecondaryButton {
            text: "Vælg …"
            onClicked: folderDialog.open()
        }
    }
    Text {
        Layout.fillWidth: true
        text: "Applikationen synkroniserer kontoens filer til denne mappe."
        font: Theme.caption
        color: Theme.textSecondary
        wrapMode: Text.Wrap
    }

    UI.InlineError {
        id: errorLabel
    }

    FolderDialog {
        id: folderDialog
        title: "Vælg synkmappe"
        onAccepted: {
            syncField.text = sheet.controller.folderToSyncDir(selectedFolder)
            sheet.syncDirEdited = true
        }
    }

    buttons: [
        UI.SecondaryButton {
            text: "Annullér"
            onClicked: sheet.close()
        },
        UI.PrimaryButton {
            text: "Tilføj og log ind"
            onClicked: sheet.submit()
        }
    ]
}
