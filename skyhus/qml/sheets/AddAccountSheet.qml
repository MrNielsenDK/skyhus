import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import Skyhus
import "../components" as UI

UI.Sheet {
    id: sheet

    required property var controller
    property bool syncDirEdited: false

    title: "Add account"

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
        text: "Display name"
        font: Theme.headline
        color: Theme.textPrimary
    }
    UI.TextField {
        id: nameField
        Layout.fillWidth: true
        placeholderText: "For example Work"
        onTextChanged: {
            if (!sheet.syncDirEdited)
                syncField.text = sheet.controller.suggestSyncDir(text)
        }
        onAccepted: sheet.submit()
    }

    Text {
        Layout.topMargin: Theme.spacingS
        text: "Sync folder"
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
            text: "Choose …"
            onClicked: folderDialog.open()
        }
    }
    Text {
        Layout.fillWidth: true
        text: "Skyhus syncs the files of the account to this folder."
        font: Theme.caption
        color: Theme.textSecondary
        wrapMode: Text.Wrap
    }

    UI.InlineError {
        id: errorLabel
    }

    FolderDialog {
        id: folderDialog
        title: "Choose sync folder"
        onAccepted: {
            syncField.text = sheet.controller.folderToSyncDir(selectedFolder)
            sheet.syncDirEdited = true
        }
    }

    buttons: [
        UI.SecondaryButton {
            text: "Cancel"
            onClicked: sheet.close()
        },
        UI.PrimaryButton {
            text: "Add and sign in"
            onClicked: sheet.submit()
        }
    ]
}
