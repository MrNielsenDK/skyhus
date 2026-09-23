import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Skyhus
import "components" as UI

// Den valgte kontos overskrift og kort.
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
                title: "Konto"

                UI.Row {
                    first: true
                    text: "Synkmappe"
                    value: page.syncDir
                }
                UI.Row {
                    text: "Status"

                    UI.StatusDot {
                        tone: page.loggedIn ? "success" : "textSecondary"
                    }
                    Text {
                        text: page.loggedIn ? "Logget ind" : "Ikke logget ind"
                        font: Theme.body
                        color: Theme.textSecondary
                    }
                }
                UI.Row {
                    text: "Log ind"
                    detail: "Log ind med kontoen i Microsofts login-side."

                    UI.SecondaryButton {
                        text: "Log ind"
                        enabled: page.controller.loginState === "idle"
                        onClicked: page.controller.login(page.confdir)
                    }
                }
                UI.Row {
                    text: "Vælg mapper"
                    detail: "Vælg, hvilke mapper på OneDrive kontoen synkroniserer."

                    UI.SecondaryButton {
                        text: "Vælg mapper …"
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

            UI.Card {
                title: "Detaljer"

                UI.Row {
                    first: true
                    text: "Visningsnavn"
                    value: page.name

                    UI.SecondaryButton {
                        text: "Omdøb"
                        onClicked: {
                            renameField.text = page.name
                            renameError.text = ""
                            renameDialog.open()
                        }
                    }
                }
                UI.Row {
                    text: "Config-mappe"
                    value: page.confdir
                }
                UI.Row {
                    text: "Service"
                    value: page.service !== "" ? page.service : "Ingen"
                }
            }
        }
    }

    UI.Sheet {
        id: renameDialog
        title: "Omdøb konto"

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
            placeholderText: "Visningsnavn"
            onAccepted: renameDialog.save()
        }
        UI.InlineError {
            id: renameError
        }

        buttons: [
            UI.SecondaryButton {
                text: "Annullér"
                onClicked: renameDialog.close()
            },
            UI.PrimaryButton {
                text: "Gem"
                onClicked: renameDialog.save()
            }
        ]
    }
}
