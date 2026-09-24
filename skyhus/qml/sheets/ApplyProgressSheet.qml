import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Templates as T
import Skyhus
import "../components" as UI

// The "Changing folder selection" sheet with the 5 steps (feature 0009). It replaces the spinner in the folder picker.
// The sheet closes when step 5 is done. If a step fails, the sheet stays open until the user clicks "Close".
// During step 2, the user can click "Stop" (feature 0010). Then the sheet stays open with a message.
UI.Sheet {
    id: sheet
    objectName: "applyProgressSheet"

    required property var controller
    readonly property bool failed: controller.applyState === "failed"
    readonly property bool cancelled: controller.applyState === "cancelled"

    closePolicy: T.Popup.NoAutoClose
    visible: controller.applyState !== ""
    title: "Changing folder selection"

    UI.StepList {
        steps: sheet.controller.applySteps
        rowName: "applyStepRow"
        stateName: "applyStepState"
        barName: "applyStepBar"
    }

    Text {
        Layout.fillWidth: true
        visible: !sheet.failed && !sheet.cancelled
        wrapMode: Text.Wrap
        text: "The upload and the resync can take a long time for a large account."
        font: Theme.caption
        color: Theme.textSecondary
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: sheet.cancelled
        spacing: Theme.spacingXS

        Text {
            objectName: "applyCancelledText"
            Layout.fillWidth: true
            visible: sheet.cancelled
            wrapMode: Text.Wrap
            text: "The change is stopped. The folder selection did not change."
            font: Theme.body
            color: Theme.textPrimary
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "Files that the client uploaded before the stop stay on OneDrive."
            font: Theme.caption
            color: Theme.textSecondary
        }
    }

    UI.InlineError {
        objectName: "applyProgressError"
        text: sheet.failed ? sheet.controller.pickerError : ""
    }

    buttons: [
        UI.SecondaryButton {
            objectName: "applyCancelButton"
            visible: sheet.controller.applyCancellable || sheet.controller.applyCancelling
            enabled: !sheet.controller.applyCancelling
            text: sheet.controller.applyCancelling ? "Stopping …" : "Stop"
            onClicked: sheet.controller.cancelApply()
        },
        UI.SecondaryButton {
            objectName: "applyProgressCloseButton"
            visible: sheet.failed || sheet.cancelled
            text: "Close"
            onClicked: sheet.controller.closeApplyProgress()
        }
    ]
}
