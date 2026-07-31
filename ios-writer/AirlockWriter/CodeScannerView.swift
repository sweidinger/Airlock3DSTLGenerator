import SwiftUI
import UIKit
import VisionKit

/// Steuert die manuelle Auslösung (Fallback) von aussen.
final class ScannerController: ObservableObject {
    var manualCapture: (() -> Void)?
    func triggerManual() { manualCapture?() }
}

/// Live-Kamera-Texterkennung (on-device) zum Abgleich der aufgedruckten
/// Lock-Nummer. Nutzt VisionKit `DataScannerViewController` — dieser arbeitet
/// prinzipbedingt nur mit der Live-Kamera (kein Foto-Upload moeglich).
///
/// Wir LESEN nicht blind, sondern GLEICHEN gegen den bekannten Code ab: ein Frame
/// gilt als Treffer, sobald der erwartete 5-stellige Code im erkannten Text steht.
/// Bei Treffer (oder manuellem Fallback) wird ein Live-Foto aufgenommen und als
/// Beleg zurueckgegeben.
struct CodeScannerView: UIViewControllerRepresentable {
    let expectedCode: String
    @ObservedObject var controller: ScannerController
    let onResult: (UIImage) -> Void

    /// Geraet unterstuetzt Live-Texterkennung + Kamera ist verfuegbar/erlaubt.
    static var isSupported: Bool {
        DataScannerViewController.isSupported && DataScannerViewController.isAvailable
    }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(
            recognizedDataTypes: [.text()],
            qualityLevel: .accurate,          // wegen kontrastarmer, vertiefter Gravur
            recognizesMultipleItems: true,
            isHighFrameRateTrackingEnabled: true,
            isPinchToZoomEnabled: true,
            isGuidanceEnabled: false,
            isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        context.coordinator.vc = vc
        controller.manualCapture = { context.coordinator.triggerManual() }
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {
        try? vc.startScanning()
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let parent: CodeScannerView
        weak var vc: DataScannerViewController?
        private var done = false
        init(_ parent: CodeScannerView) { self.parent = parent }

        func dataScanner(_ scanner: DataScannerViewController,
                         didAdd addedItems: [RecognizedItem],
                         allItems: [RecognizedItem]) { check(allItems) }

        func dataScanner(_ scanner: DataScannerViewController,
                         didUpdate updatedItems: [RecognizedItem],
                         allItems: [RecognizedItem]) { check(allItems) }

        private func check(_ items: [RecognizedItem]) {
            guard !done else { return }
            for case let .text(text) in items {
                let onlyDigits = text.transcript.filter(\.isNumber)
                if text.transcript.contains(parent.expectedCode)
                    || onlyDigits.contains(parent.expectedCode) {
                    done = true
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                    capture()
                    return
                }
            }
        }

        /// Manueller Auslöser (Fallback nach einigen Sekunden ohne Treffer).
        func triggerManual() {
            guard !done else { return }
            done = true
            capture()
        }

        private func capture() {
            guard let vc else { return }
            Task { @MainActor in
                let image = try? await vc.capturePhoto()
                vc.stopScanning()
                if let image { parent.onResult(image) }
            }
        }
    }
}

extension UIImage {
    /// Verkleinert (lange Kante <= maxDimension) und komprimiert als JPEG fuers
    /// Hochladen — haelt den Beleg typ. unter ~300 KB.
    func jpegForUpload(maxDimension: CGFloat = 1024, quality: CGFloat = 0.7) -> Data? {
        let longSide = max(size.width, size.height)
        let factor = longSide > maxDimension ? maxDimension / longSide : 1
        let target = CGSize(width: size.width * factor, height: size.height * factor)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: target, format: format).image { _ in
            draw(in: CGRect(origin: .zero, size: target))
        }
        return resized.jpegData(compressionQuality: quality)
    }
}
