import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Skyhus
import "components" as UI

// The heading and cards of the selected account.
Item {
    id: page

    required property var controller
    property string name
    property string confdir
    property string syncDir
    property string service
    property bool loggedIn
    property string initials
    property color avatarColor: Theme.accent
    property color avatarTextColor: Theme.onAccent
    property string serviceLabel
    property string serviceTone: "textSecondary"
    property string serviceSince
    property string serviceError
    property string serviceAction
    property string serviceActionLabel
    property bool serviceBusy: false
    property string serviceMessage
    property var serviceProgress: ({})
    property bool serviceCancellable: false

    // The card "Activity" reads the journal of the account on the page (feature 0019).
    onConfdirChanged: controller.openActivity(confdir)
    Component.onCompleted: controller.openActivity(confdir)

    Flickable {
        id: flick
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: column.implicitHeight + 2 * Theme.spacingXL
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column
            width: Math.min(Theme.contentWidth, flick.width - 2 * Theme.spacingXL)
            x: Math.round((flick.width - width) / 2)
            y: Theme.spacingXL
            spacing: Theme.spacingXL

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingL

                UI.Avatar {
                    size: Theme.avatarLarge
                    initials: page.initials
                    color: page.avatarColor
                    textColor: page.avatarTextColor
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingXS

                    Text {
                        Layout.fillWidth: true
                        text: page.name
                        font: Theme.largeTitle
                        color: Theme.textPrimary
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.syncDir
                        font: Theme.body
                        color: Theme.textSecondary
                        elide: Text.ElideMiddle
                    }
                }
            }

            UI.Card {
                title: "Account"

                UI.Row {
                    first: true
                    text: "Sync folder"
                    value: page.syncDir
                }
                UI.Row {
                    text: "Status"

                    UI.StatusDot {
                        tone: page.loggedIn ? "success" : "textSecondary"
                    }
                    Text {
                        text: page.loggedIn ? "Signed in" : "Not signed in"
                        font: Theme.body
                        color: Theme.textSecondary
                    }
                }
                UI.Row {
                    text: "Sign in"
                    detail: "Sign in with the account on the Microsoft sign-in page."

                    UI.SecondaryButton {
                        text: "Sign in"
                        enabled: page.controller.loginState === "idle"
                        onClicked: page.controller.login(page.confdir)
                    }
                }
                UI.Row {
                    text: "Choose folders"
                    detail: "Choose which folders on OneDrive the account syncs."

                    UI.SecondaryButton {
                        text: "Choose folders …"
                        enabled: page.controller.loginState === "idle" && page.controller.pickerState === "closed"
                        onClicked: page.controller.openFolderPicker(page.confdir)
                    }
                }
            }

            UI.ServiceCard {
                stateLabel: page.serviceLabel
                tone: page.serviceTone
                since: page.serviceSince
                errorLine: page.serviceError
                action: page.serviceAction
                actionLabel: page.serviceActionLabel
                busy: page.serviceBusy
                message: page.serviceMessage
                progress: page.serviceProgress
                cancellable: page.serviceCancellable
                onActionClicked: page.controller.serviceAction(page.confdir)
                onCancelResyncClicked: page.controller.requestCancelResync(page.confdir)
            }

            UI.ActivityCard {
                controller: page.controller
            }

            UI.Card {
                title: "Details"

                UI.Row {
                    first: true
                    text: "Display name"
                    value: page.name

                    UI.SecondaryButton {
                        text: "Rename"
                        onClicked: {
                            renameField.text = page.name
                            renameError.text = ""
                            renameDialog.open()
                        }
                    }
                }
                UI.Row {
                    text: "Config folder"
                    value: page.confdir
                }
                UI.Row {
                    text: "Service"
                    value: page.service !== "" ? page.service : "None"
                }
            }

            // Remove the account (feature 0018).
            UI.Card {
                title: "Remove"

                UI.Row {
                    first: true
                    text: "Remove account"
                    detail: "Disable the service and move the account's folders to the Trash. The files on OneDrive stay."

                    UI.SecondaryButton {
                        objectName: "removeAccountButton"
                        destructive: true
                        text: "Remove account …"
                        enabled: page.controller.loginState === "idle" && page.controller.pickerState === "closed"
                                 && page.controller.removeState === "" && !page.serviceBusy
                        onClicked: page.controller.requestRemoveAccount(page.confdir)
                    }
                }
            }
        }
    }

    UI.Sheet {
        id: renameDialog
        title: "Rename account"

        function save() {
            var error = page.controller.rename(page.confdir, renameField.text)
            if (error !== "")
                renameError.text = error
            else
                renameDialog.close()
        }

        onOpened: renameField.forceActiveFocus()

        UI.TextField {
            id: renameField
            Layout.fillWidth: true
            placeholderText: "Display name"
            onAccepted: renameDialog.save()
        }
        UI.InlineError {
            id: renameError
        }

        buttons: [
            UI.SecondaryButton {
                text: "Cancel"
                onClicked: renameDialog.close()
            },
            UI.PrimaryButton {
                text: "Save"
                onClicked: renameDialog.save()
            }
        ]
    }
}
