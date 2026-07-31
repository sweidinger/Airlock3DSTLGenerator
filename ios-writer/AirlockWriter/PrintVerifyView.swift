import SwiftUI
import UIKit

/// Tab „Drucken": listet druckbereite Locks (Status `generated`), erfasst die
/// aufgedruckte Nummer per Live-Kamera, setzt bei Treffer `generated -> printed`
/// (mit Foto-Beleg) und bietet direkt das Tag-Schreiben an (Verkettung).
struct PrintVerifyView: View {
    @EnvironmentObject var settings: SettingsStore
    @StateObject private var writer = NFCWriterService()

    @State private var airlocks: [Airlock] = []
    @State private var loading = false
    @State private var message: String?
    @State private var isError = false
    @State private var scanLock: Airlock?
    @State private var writePrompt: Airlock?
    @State private var showWritePrompt = false

    private var api: AirlockAPI { AirlockAPI(connection: settings.connection) }

    var body: some View {
        NavigationStack {
            Group {
                if !settings.connection.isConfigured {
                    ContentUnavailableView {
                        Label("Nicht eingerichtet", systemImage: "key.slash")
                    } description: {
                        Text("Basis-URL und Writer-Key im Tab „Schreiben“ → Einstellungen eintragen.")
                    }
                } else {
                    list
                }
            }
            .navigationTitle("Drucken prüfen")
            .overlay(alignment: .top) { messageBar }
            .refreshable { await reload() }
            .task { await reload() }
            .fullScreenCover(item: $scanLock) { lock in
                ScanSheet(expectedCode: lock.code) { image in
                    scanLock = nil
                    Task { await confirmPrinted(lock, image: image) }
                } onCancel: {
                    scanLock = nil
                }
            }
            .alert("Tag jetzt schreiben?", isPresented: $showWritePrompt, presenting: writePrompt) { lock in
                Button("Tag schreiben") { Task { await writeTag(lock) } }
                Button("Später", role: .cancel) {}
            } message: { lock in
                Text("Lock \(lock.code) ist als gedruckt markiert. Direkt den NFC-Tag beschreiben?")
            }
        }
    }

    private var list: some View {
        List {
            Section {
                if airlocks.isEmpty && !loading {
                    Text("Keine druckbereiten Locks (Status „generated“).")
                        .foregroundStyle(.secondary)
                }
                ForEach(airlocks) { lock in
                    Button { scanLock = lock } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(lock.code).font(.headline.monospaced())
                                Text(lock.status).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "camera.viewfinder").foregroundStyle(.tint)
                        }
                    }
                    .buttonStyle(.plain)
                }
            } header: {
                Text("\(airlocks.count) druckbereit (generated)")
            } footer: {
                Text("Lock antippen, dann die aufgedruckte Nummer mit der Kamera erfassen. Bei Treffer wird der Lock auf „gedruckt“ gesetzt und das Foto als Beleg gespeichert.")
            }
        }
        .overlay { if loading { ProgressView() } }
    }

    @ViewBuilder private var messageBar: some View {
        if let message {
            Text(message)
                .font(.callout).padding(12).frame(maxWidth: .infinity)
                .background(isError ? Color.red.opacity(0.9) : Color.green.opacity(0.9))
                .foregroundStyle(.white)
                .transition(.move(edge: .top))
        }
    }

    private func reload() async {
        guard settings.connection.isConfigured else { return }
        loading = true; defer { loading = false }
        do {
            let all = try await api.listAirlocks()
            airlocks = all.filter { $0.status == "generated" }
        } catch {
            show(error.localizedDescription, error: true)
        }
    }

    private func confirmPrinted(_ lock: Airlock, image: UIImage) async {
        guard let jpeg = image.jpegForUpload() else {
            show("Foto konnte nicht verarbeitet werden.", error: true)
            return
        }
        do {
            try await api.markPrinted(code: lock.code, jpeg: jpeg)
            show("Lock \(lock.code) als gedruckt markiert ✓", error: false)
            await reload()
            writePrompt = lock
            showWritePrompt = true
        } catch {
            show("Konnte nicht als gedruckt markieren: \(error.localizedDescription)", error: true)
        }
    }

    private func writeTag(_ lock: Airlock) async {
        do {
            let r = try await writer.write(code: lock.code, api: api)
            show("Tag geschrieben & gebunden ✓ (Lock \(r.code))", error: false)
            await reload()
        } catch {
            show("Schreiben fehlgeschlagen: \(error.localizedDescription)", error: true)
        }
    }

    private func show(_ text: String, error: Bool) {
        withAnimation { message = text; isError = error }
        Task {
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            withAnimation { if message == text { message = nil } }
        }
    }
}

/// Vollbild-Kamera mit Ziel-Overlay, Abbrechen und (nach einigen Sekunden) einem
/// manuellen Bestaetigungs-Button als Fallback. Nimmt in beiden Faellen ein
/// Live-Foto als Beleg auf.
private struct ScanSheet: View {
    let expectedCode: String
    let onResult: (UIImage) -> Void
    let onCancel: () -> Void

    @StateObject private var controller = ScannerController()
    @State private var showFallback = false

    var body: some View {
        ZStack {
            if CodeScannerView.isSupported {
                CodeScannerView(expectedCode: expectedCode,
                                controller: controller,
                                onResult: onResult)
                    .ignoresSafeArea()
            } else {
                Color.black.ignoresSafeArea()
                ContentUnavailableView {
                    Label("Kamera nicht verfügbar", systemImage: "camera.metering.unknown")
                } description: {
                    Text("Dieses Gerät unterstützt die Live-Texterkennung nicht oder der Kamerazugriff wurde verweigert.")
                }
                .foregroundStyle(.white)
            }

            VStack {
                Text("Nummer \(expectedCode) in den Rahmen halten")
                    .font(.headline)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(.ultraThinMaterial, in: Capsule())
                    .padding(.top, 16)
                Spacer()
                HStack {
                    Button("Abbrechen") { onCancel() }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(.ultraThinMaterial, in: Capsule())
                    Spacer()
                    if showFallback {
                        Button {
                            controller.triggerManual()
                        } label: {
                            Label("Nummer stimmt", systemImage: "checkmark")
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(Color.yellow.opacity(0.92), in: Capsule())
                        .foregroundStyle(.black)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 28)
            }
        }
        .task {
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            withAnimation { showFallback = true }
        }
    }
}
