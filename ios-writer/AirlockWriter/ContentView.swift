import SwiftUI

struct ContentView: View {
    @EnvironmentObject var settings: SettingsStore
    @StateObject private var writer = NFCWriterService()

    @State private var airlocks: [Airlock] = []
    @State private var loading = false
    @State private var message: String?
    @State private var isError = false
    @State private var showSettings = false

    private var api: AirlockAPI { AirlockAPI(connection: settings.connection) }

    var body: some View {
        NavigationStack {
            Group {
                if !settings.connection.isConfigured {
                    unconfiguredView
                } else {
                    listView
                }
            }
            .navigationTitle("Airlock Writer")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView().environmentObject(settings) }
            .overlay(alignment: .bottom) { messageBar }
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
                Text("\(airlocks.count) Airlock(s)")
            }
        }
        .refreshable { await reload() }
        .overlay { if loading { ProgressView() } }
    }

    @ViewBuilder private var messageBar: some View {
        if let message {
            Text(message)
                .font(.callout)
                .padding(12)
                .frame(maxWidth: .infinity)
                .background(isError ? Color.red.opacity(0.9) : Color.green.opacity(0.9))
                .foregroundStyle(.white)
                .transition(.move(edge: .bottom))
        }
    }

    private func reload() async {
        guard settings.connection.isConfigured else { return }
        loading = true; defer { loading = false }
        do { airlocks = try await api.listAirlocks() }
        catch { show(error.localizedDescription, error: true) }
    }

    private func writeTag(for lock: Airlock) async {
        do {
            let result = try await writer.write(code: lock.code, api: api)
            show("Tag geschrieben & gebunden ✓ (\(result.uid))", error: false)
            await reload()
        } catch {
            show(error.localizedDescription, error: true)
        }
    }

    private func show(_ text: String, error: Bool) {
        withAnimation { message = text; isError = error }
        Task {
            try? await Task.sleep(nanoseconds: 3_500_000_000)
            withAnimation { if message == text { message = nil } }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Airlock-Server") {
                    TextField("https://10.0.1.9:8453", text: $settings.baseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                Section("Writer-Key") {
                    SecureField("alw_…", text: $settings.writerKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Im Airlock-Dashboard unter „KG-Tracker" → „Writer-Keys" erzeugen. Der Key wird nur im iOS-Keychain gespeichert.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Einstellungen")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") { dismiss() }
                }
            }
        }
    }
}
