import SwiftUI

/// First-run screen: enter the LumiRSS server address. The address is
/// normalized (origin only), probed against /api/v1/version and only
/// accepted when the server is compatible.
struct ServerSetupView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var address = ""
    @State private var isChecking = false

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "rss")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
            VStack(spacing: 6) {
                Text("LumiRSS")
                    .font(.title.bold())
                Text(String(localized: "连接你的 LumiRSS 服务器"))
                    .foregroundStyle(.secondary)
            }
            TextField(String(localized: "https://your-server.example.com"), text: $address)
                .textFieldStyle(.roundedBorder)
                .textContentType(.URL)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .padding(.horizontal, 32)
                .onSubmit { Task { await check() } }
            if let error = environment.session.lastError {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
            Button {
                Task { await check() }
            } label: {
                if isChecking {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                } else {
                    Text(String(localized: "连接"))
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty || isChecking)
            .padding(.horizontal, 32)
            if let version = environment.session.serverVersion {
                Text(String(localized: "服务器版本 \(version.version)"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Spacer()
        }
        .accessibilityElement(children: .contain)
    }

    private func check() async {
        isChecking = true
        defer { isChecking = false }
        await environment.session.configureServer(address)
    }
}
