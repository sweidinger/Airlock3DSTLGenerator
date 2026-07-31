import SwiftUI

struct ContentView: View {
    @EnvironmentObject var settings: SettingsStore
    @StateObject private var writer = NFCWriterService()
    @StateObject private var reader = NFCReaderService()

    @State private var airlocks: [Airlock] = []
    @State private var loading = false
    @State private var message: String?
    @State private var isError = false
    @State private var showSettings = false
    @State private var rebindLock: Airlock?
    @State private var showRebind = false
    @State private var logLines: [LogEntry] = []

    private var api: AirlockAPI { AirlockAPI(connection: settings.connection) }

    var body: some View {
        NavigationStack {
            Group {
                if !settings.connection.isConfigured {
                    unconfiguredView
                } else {
                    VStack(spacing: 0) {
                        listView
                        logBox
                    }
                }
            }
            .navigationTitle("Airlock Writer")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { Task { await verifyTag() } } label: {
                        Label("Tag lesen", systemImage: "wave.3.right.circle")
                    }
                    .disabled(!settings.connection.isConfigured)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView().environmentObject(settings) }
            .overlay(alignment: .top) { messageBar }
            .alert("Neu verheiraten?", isPresented: $showRebind, presenting: rebindLock) { lock in
                Button("Neu verheiraten", role: .destructive) {
                    Task { await writeTag(for: lock, rebind: true) }
                }
                Button("Abbrechen", role: .cancel) {}
            } message: { _ in
                Text("Dieses Schloss oder der Tag ist bereits gebunden. Eine Bindung ist eigentlich endgültig — nur während der Beta lässt sie sich ersetzen.")
            }
        }
        .task { await reload() }
    }

    private var unconfiguredView: some View {
        ContentUnavailableView {
            Label("Nicht eingerichtet", systemImage: "key.slash")
        } description: {
            Text("Basis-URL und Writer-Key (alw_…) in den Einstellungen eintragen.")
        } actions: {
            Button("Einstellungen öffnen") { showSettings = true }
        }
    }

    private var listView: some View {
        List {
            Section {
                ForEach(airlocks) { lock in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(lock.code).font(.headline.monospaced())
                            Text(lock.status).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if lock.hasTag {
                            Label("Tag", systemImage: "checkmark.seal.fill")
                                .labelStyle(.iconOnly).foregroundStyle(.green)
                        }
                        Button("Schreiben") { Task { await writeTag(for: lock) } }
                            .buttonStyle(.borderedProminent)
                    }
                }
            } header: {
                Text("\(airlocks.count) druckbereite(r) Airlock(s)")
            } footer: {
                Text("Nur Locks ab Status gedruckt werden angezeigt (vorher darf kein Tag geschrieben werden). Tag lesen (oben links) prüft einen beliebigen Tag zurück.")
            }
        }
        .refreshable { await reload() }
        .overlay { if loading { ProgressView() } }
    }

    private var logBox: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label("Log", systemImage: "list.bullet.rectangle")
                    .font(.caption.bold()).foregroundStyle(.secondary)
                Spacer()
                Button("Leeren") { logLines.removeAll() }
                    .font(.caption).disabled(logLines.isEmpty)
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 3) {
                    if logLines.isEmpty {
                        Text("Noch keine Aktionen.")
                            .font(.caption).foregroundStyle(.secondary).padding(.vertical, 6)
                    } else {
                        ForEach(logLines) { e in
                            Text(e.text)
                                .font(.caption2.monospaced())
                                .foregroundStyle(color(for: e.kind))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .textSelection(.enabled)
                        }
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 6)
            }
        }
        .frame(height: 175)
        .background(.ultraThinMaterial)
        .overlay(Divider(), alignment: .top)
    }

    @ViewBuilder private var messageBar: some View {
        if let message {
            Text(message)
                .font(.callout)
                .padding(12)
                .frame(maxWidth: .infinity)
                .background(isError ? Color.red.opacity(0.9) : Color.green.opacity(0.9))
                .foregroundStyle(.white)
                .transition(.move(edge: .top))
        }
    }

    private func color(for kind: LogEntry.Kind) -> Color {
        switch kind {
        case .ok: return .green
        case .err: return .red
        case .info: return .secondary
        }
    }

    private func reload() async {
        guard settings.connection.isConfigured else { return }
        loading = true; defer { loading = false }
        do {
            let all = try await api.listAirlocks()
            // Nur druckbereite/beschriebene Locks: ab 'printed'. reserved/generated
            // sind noch nicht beschreibbar; terminale (retired/voided) ausgeblendet.
            airlocks = all.filter { ["printed", "registered", "active"].contains($0.status) }
        } catch {
            show(error.localizedDescription, error: true)
        }
    }

    private func writeTag(for lock: Airlock, rebind: Bool = false) async {
        logAppend("Schreibe Lock \(lock.code)…", .info)
        do {
            let result = try await writer.write(code: lock.code, api: api, rebind: rebind)
            show("Tag geschrieben & gebunden ✓ (Lock \(result.code))", error: false)
            logAppend("✓ Lock \(result.code) geschrieben & gebunden — UID \(result.uid)", .ok)
            await reload()
        } catch {
            // 409 = Schloss/Tag schon gebunden -> Neu-Verheiraten anbieten (Beta).
            if case let APIError.http(status, _) = error, status == 409, !rebind {
                rebindLock = lock
                showRebind = true
            } else {
                show(error.localizedDescription, error: true)
                logAppend("✗ Schreiben fehlgeschlagen (Lock \(lock.code)): \(error.localizedDescription)", .err)
            }
        }
    }

    private func verifyTag() async {
        logAppend("Tag lesen…", .info)
        do {
            let r = try await reader.read(api: api)
            appendReport(r)
        } catch {
            show(error.localizedDescription, error: true)
            logAppend("✗ Lesefehler: \(error.localizedDescription)", .err)
        }
    }

    private func appendReport(_ r: TagReport) {
        if let s = r.server, s.valid, let code = s.code ?? r.code {
            show("Lock \(code) gefunden ✓ (Status: \(s.status ?? "?"))", error: false)
            logAppend("✓ Lock \(code) gefunden — Status \(s.status ?? "?"), Tag gültig. UID \(r.uid)", .ok)
        } else if let s = r.server {
            let reason = s.reason ?? "ungültig"
            let codeInfo = r.code.map { " (Code \($0))" } ?? ""
            show("Tag ungültig: \(reason)", error: true)
            logAppend("✗ Tag ungültig — Grund: \(reason)\(codeInfo). UID \(r.uid)", .err)
        } else {
            let note = r.note ?? "Kein Airlock-Datensatz auf dem Tag."
            show(note, error: true)
            logAppend("✗ \(note) UID \(r.uid)", .err)
        }
        logAppend("   NDEF: \(r.recordType); Text: \(r.decodedText ?? "—")", .info)
        if !r.rawHex.isEmpty { logAppend("   Roh(hex): \(r.rawHex)", .info) }
    }

    private func logAppend(_ text: String, _ kind: LogEntry.Kind) {
        logLines.insert(LogEntry(text: text, kind: kind), at: 0)
        if logLines.count > 60 { logLines.removeLast(logLines.count - 60) }
    }

    private func show(_ text: String, error: Bool) {
        withAnimation { message = text; isError = error }
        Task {
            try? await Task.sleep(nanoseconds: 8_500_000_000)
            withAnimation { if message == text { message = nil } }
        }
    }
}

/// Eine Zeile im App-Log (Debug/Info am unteren Rand).
struct LogEntry: Identifiable {
    enum Kind { case info, ok, err }
    let id = UUID()
    let text: String
    let kind: Kind
}

struct SettingsView: View {
    @EnvironmentObject var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss

    // Entwurf: erst „Speichern" schreibt in den Store (Abbrechen verwirft).
    @State private var baseURL = ""
    @State private var writerKey = ""
    @State private var testing = false
    @State private var testMessage: String?
    @State private var testOK = false

    private var draft: Connection { Connection(baseURL: baseURL, writerKey: writerKey) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://10.0.1.9:8453", text: $baseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                } header: {
                    Text("Airlock-Server")
                } footer: {
                    Text("Die eigene Server-Adresse eintragen (z. B. https://10.0.1.9:8453). Der graue Text im Feld ist nur ein Beispiel-Platzhalter, kein Wert.")
                }

                Section {
                    SecureField("alw_…", text: $writerKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Writer-Key")
                } footer: {
                    Text("Im Airlock-Dashboard unter \"KG-Tracker\" \u{2192} \"Writer-Keys\" erzeugen. Der Key wird nur im iOS-Keychain gespeichert.")
                }

                Section {
                    Button {
                        Task { await testConnection() }
                    } label: {
                        HStack {
                            Label("Verbindung testen", systemImage: "antenna.radiowaves.left.and.right")
                            Spacer()
                            if testing { ProgressView() }
                        }
                    }
                    .disabled(testing || !draft.isConfigured)

                    if let testMessage {
                        Label(testMessage, systemImage: testOK ? "checkmark.circle.fill" : "xmark.octagon.fill")
                            .foregroundStyle(testOK ? .green : .red)
                            .font(.callout)
                    }
                }
            }
            .navigationTitle("Einstellungen")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { save(); dismiss() }
                        .disabled(!draft.isConfigured)
                }
            }
            .onAppear {
                baseURL = settings.baseURL
                writerKey = settings.writerKey
            }
        }
    }

    private func save() {
        settings.baseURL = draft.trimmedBaseURL
        settings.writerKey = draft.trimmedWriterKey
    }

    private func testConnection() async {
        testing = true
        testMessage = nil
        defer { testing = false }
        do {
            let locks = try await AirlockAPI(connection: draft).listAirlocks()
            testOK = true
            testMessage = "Verbindung OK – \(locks.count) Airlock(s) gefunden."
        } catch {
            testOK = false
            testMessage = friendlyMessage(for: error)
        }
    }

    private func friendlyMessage(for error: Error) -> String {
        if case let APIError.http(code, _) = error {
            if code == 401 { return "Writer-Key abgelehnt (401). Stimmt der Key?" }
            return "Server antwortete mit HTTP \(code)."
        }
        if let urlError = error as? URLError {
            return "Keine Verbindung: \(urlError.localizedDescription)"
        }
        return error.localizedDescription
    }
}
