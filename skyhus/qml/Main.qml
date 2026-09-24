import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "components" as UI
import "sheets"

ApplicationWindow {
    id: window

    required property var controller
    // Safe mode (feature 0007). app.py gives the value at start.
    property bool safeMode: false

    readonly property var loginActiveStates: ["starting", "waiting_for_user", "waiting_for_token", "activating",
                                              "cancelling"]
    readonly property bool loginActive: loginActiveStates.indexOf(controller.loginState) >= 0

    width: Theme.windowWidth
    height: Theme.windowHeight
    minimumWidth: Theme.windowMinWidth
    minimumHeight: Theme.windowMinHeight
    visible: true
    title: "Skyhus"
    color: Theme.windowBg
    font: Theme.body

    header: UI.SafeModeBanner {
        visible: window.safeMode
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // The sidebar with all accounts and the "Add account" button at the bottom.
        Rectangle {
            id: sidebar
            objectName: "sidebar"
            Layout.preferredWidth: Theme.sidebarWidth
            Layout.fillHeight: true
            color: Theme.sidebarBg

            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                width: Theme.hairline
                color: Theme.separator
            }

            // The list goes to the edge minus the focus ring. Then the ring is not cut off.
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingM - Theme.focusRing
                spacing: Theme.spacingS

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.focusRing
                    leftPadding: Theme.spacingS
                    topPadding: Theme.spacingXS
                    text: "Accounts"
                    font: Theme.caption
                    color: Theme.textSecondary
                }

                ListView {
                    id: accountList
                    objectName: "accountList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: Theme.hairline
                    leftMargin: Theme.focusRing
                    rightMargin: Theme.focusRing
                    topMargin: Theme.focusRing
                    bottomMargin: Theme.focusRing
                    activeFocusOnTab: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: window.controller.accounts

                    delegate: T.ItemDelegate {
                        id: row
                        objectName: "sidebarRow"

                        required property int index
                        required property string name
                        required property string confdir
                        required property string syncDir
                        required property string service
                        required property bool loggedIn
                        required property string initials
                        required property string avatarColor
                        required property string avatarTextColor
                        required property string serviceLabel
                        required property string serviceTone
                        required property string serviceSince
                        required property string serviceError
                        required property string serviceAction
                        required property string serviceActionLabel
                        required property bool serviceBusy
                        required property string serviceMessage
                        required property var serviceProgress
                        required property bool serviceCancellable

                        width: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
                        implicitHeight: Theme.sidebarRowHeight
                        leftPadding: Theme.spacingS
                        rightPadding: Theme.spacingS
                        focusPolicy: Qt.NoFocus
                        highlighted: ListView.isCurrentItem
                        onClicked: accountList.currentIndex = index

                        background: Rectangle {
                            radius: Theme.radiusControl
                            color: row.highlighted ? Theme.accent : row.hovered ? Theme.hover : Theme.transparent

                            Behavior on color {
                                ColorAnimation { duration: Theme.animFast; easing.type: Theme.animEasing }
                            }

                            UI.FocusRing {
                                shown: row.highlighted && accountList.activeFocus
                            }
                        }

                        contentItem: RowLayout {
                            spacing: Theme.spacingS

                            UI.Avatar {
                                initials: row.initials
                                color: row.avatarColor
                                textColor: row.avatarTextColor
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.name
                                font: Theme.headline
                                color: row.highlighted ? Theme.onAccent : Theme.textPrimary
                                elide: Text.ElideRight
                            }
                            UI.StatusDot {
                                objectName: "sidebarStatusDot"
                                tone: row.serviceTone
                                outlined: row.highlighted
                            }
                        }
                    }
                }

                UI.SecondaryButton {
                    Layout.fillWidth: true
                    Layout.margins: Theme.focusRing
                    iconName: "plus"
                    text: "Add account"
                    enabled: !window.loginActive
                    onClicked: addSheet.open()
                }
            }
        }

        // The content area with the details of the selected account.
        Rectangle {
            id: content
            objectName: "content"
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.windowBg

            AccountPage {
                objectName: "accountPage"
                anchors.fill: parent
                controller: window.controller
                visible: accountList.currentItem !== null
                name: accountList.currentItem ? accountList.currentItem.name : ""
                confdir: accountList.currentItem ? accountList.currentItem.confdir : ""
                syncDir: accountList.currentItem ? accountList.currentItem.syncDir : ""
                service: accountList.currentItem ? accountList.currentItem.service : ""
                loggedIn: accountList.currentItem ? accountList.currentItem.loggedIn : false
                initials: accountList.currentItem ? accountList.currentItem.initials : ""
                avatarColor: accountList.currentItem ? accountList.currentItem.avatarColor : Theme.accent
                avatarTextColor: accountList.currentItem ? accountList.currentItem.avatarTextColor : Theme.onAccent
                serviceLabel: accountList.currentItem ? accountList.currentItem.serviceLabel : ""
                serviceTone: accountList.currentItem ? accountList.currentItem.serviceTone : "textSecondary"
                serviceSince: accountList.currentItem ? accountList.currentItem.serviceSince : ""
                serviceError: accountList.currentItem ? accountList.currentItem.serviceError : ""
                serviceAction: accountList.currentItem ? accountList.currentItem.serviceAction : ""
                serviceActionLabel: accountList.currentItem ? accountList.currentItem.serviceActionLabel : ""
                serviceBusy: accountList.currentItem ? accountList.currentItem.serviceBusy : false
                serviceMessage: accountList.currentItem ? accountList.currentItem.serviceMessage : ""
                serviceProgress: accountList.currentItem ? accountList.currentItem.serviceProgress : ({})
                serviceCancellable: accountList.currentItem ? accountList.currentItem.serviceCancellable : false
            }

            // The empty state when there are no accounts.
            ColumnLayout {
                objectName: "emptyState"
                anchors.centerIn: parent
                width: Math.min(parent.width - 2 * Theme.spacingXL, Theme.sheetWidth)
                visible: accountList.count === 0
                spacing: Theme.spacingM

                UI.Icon {
                    Layout.alignment: Qt.AlignHCenter
                    name: "users"
                    size: Theme.iconLarge
                    color: Theme.textSecondary
                }
                Text {
                    objectName: "emptyLabel"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: "No accounts yet"
                    font: Theme.title
                    color: Theme.textPrimary
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Add a OneDrive account to sync its files."
                    font: Theme.body
                    color: Theme.textSecondary
                }
                UI.PrimaryButton {
                    objectName: "emptyAddButton"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: Theme.spacingS
                    text: "Add account"
                    enabled: !window.loginActive
                    onClicked: addSheet.open()
                }
            }
        }
    }

    AddAccountSheet {
        id: addSheet
        controller: window.controller
    }

    FolderPickerSheet {
        controller: window.controller
    }

    ApplyProgressSheet {
        controller: window.controller
    }

    ConfirmRemovalSheet {
        controller: window.controller
    }

    ConfirmResyncSheet {
        controller: window.controller
    }

    ConfirmCancelResyncSheet {
        controller: window.controller
    }

    RemoveAccountSheet {
        controller: window.controller
    }

    AllFilesSheet {
        controller: window.controller
    }

    ClosingSheet {
        controller: window.controller
    }

    UI.Sheet {
        id: loginPopup
        objectName: "loginPopup"
        preferredWidth: parent.width
        height: parent.height - Theme.spacingXL
        closePolicy: T.Popup.NoAutoClose
        visible: window.loginActive
        title: "Sign in: " + window.controller.loginAccountName

        // Feature 0005: the flow has stopped the service of the account during sign-in.
        Text {
            objectName: "loginNote"
            Layout.fillWidth: true
            visible: text !== ""
            wrapMode: Text.Wrap
            text: window.controller.loginNote
            font: Theme.body
            color: Theme.textSecondary
        }

        Loader {
            id: loginLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            active: window.controller.loginState === "waiting_for_user"
            visible: active
            source: "sheets/LoginSheet.qml"
            onLoaded: {
                item.authUrl = Qt.binding(function() { return window.controller.authUrl })
                item.redirectCaptured.connect(function(url) { window.controller.submitRedirect(url) })
            }
        }

        UI.InlineError {
            text: loginLoader.active && loginLoader.status === Loader.Error
                  ? "The sign-in window needs QtWebEngine. Install the package python3-pyside6.qtwebenginequick."
                  : ""
        }

        Item {
            visible: !loginLoader.active
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.centerIn: parent
                width: parent.width
                spacing: Theme.spacingM

                BusyIndicator {
                    Layout.alignment: Qt.AlignHCenter
                    running: loginPopup.visible && !loginLoader.active
                    palette.dark: Theme.textSecondary
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font: Theme.body
                    color: Theme.textSecondary
                    text: {
                        switch (window.controller.loginState) {
                        case "starting": return "Starting onedrive …"
                        case "waiting_for_token": return "Saving the sign-in …"
                        case "activating": return "Starting the service …"
                        case "cancelling": return "Cancelling …"
                        default: return ""
                        }
                    }
                }
            }
        }

        buttons: [
            UI.SecondaryButton {
                objectName: "cancelLoginButton"
                text: window.controller.loginState === "cancelling" ? "Cancelling …" : "Cancel"
                enabled: window.controller.loginState !== "activating"
                         && window.controller.loginState !== "cancelling"
                onClicked: window.controller.cancelLogin()
            }
        ]
    }

    UI.Sheet {
        id: messageDialog
        objectName: "messageDialog"
        title: "Skyhus"
        onClosed: window.controller.clearMessage()

        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: window.controller.message
            font: Theme.body
            color: Theme.textPrimary
        }

        buttons: [
            UI.PrimaryButton {
                text: "OK"
                onClicked: messageDialog.close()
            }
        ]
    }

    Connections {
        target: window.controller
        function onMessageChanged() {
            if (window.controller.message !== "")
                messageDialog.open()
        }
        // Feature 0008: the actions are done, or the user clicked "Close anyway".
        function onCloseReady() {
            window.close()
        }
    }

    // The service status updates only while the window is visible and not minimized.
    function updateStatusTimer() {
        window.controller.setWindowVisible(window.visibility !== Window.Minimized
                                           && window.visibility !== Window.Hidden)
    }

    onVisibilityChanged: updateStatusTimer()
    Component.onCompleted: updateStatusTimer()
    // The window waits for actions that stop or start a service (feature 0008).
    // app.py calls controller.shutdown() when the window is closed.
    onClosing: function(close) {
        close.accepted = window.controller.requestClose()
    }
}
