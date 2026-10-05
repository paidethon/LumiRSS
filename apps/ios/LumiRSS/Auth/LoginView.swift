import SwiftUI

/// Username + password login against the configured server. TOTP
/// (when the account has it enabled) surfaces a second factor field
/// served by the same server-side flow as the web client.
struct LoginView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var username = ""
    @State private var password = ""
    @State private var totpCode = ""
    @State private var isWorking = false

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                Spacer(minLength: 24)
                Image(systemName: "person.crop.circle")
                    .font(.system(size: 52))
                    .foregroundStyle(.tint)
                if let origin = environment.session.serverOrigin {
                    Text(origin.absoluteString)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                VStack(spacing: 12) {
                    TextField(String(localized: "用户名"), text: $username)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.username)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    SecureField(String(localized: "密码"), text: $password)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.password)
                        .onSubmit { Task { await submit() } }
                    if environment.session.awaitingTOTP {
                        SecureField(String(localized: "两步验证码"), text: $totpCode)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.oneTimeCode)
                            .keyboardType(.numberPad)
                            .onSubmit { Task { await submit() } }
                    }
                }
                .padding(.horizontal, 32)

                if let error = environment.session.lastError {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }

                Button {
                    Task { await submit() }
                } label: {
                    if isWorking {
                        ProgressView().frame(maxWidth: .infinity)
                    } else {
                        Text(environment.session.awaitingTOTP
                             ? String(localized: "验证并登录")
                             : String(localized: "登录"))
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(isWorking || username.isEmpty || password.isEmpty)
                .padding(.horizontal, 32)

                Button(String(localized: "更换服务器")) {
                    Task {
                        await environment.session.logout()
                        environment.session.forgetServer()
                    }
                }
                .font(.footnote)
                Spacer(minLength: 24)
            }
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    private func submit() async {
        isWorking = true
        defer { isWorking = false }
        await environment.session.login(
            username: username,
            password: password,
            totpCode: environment.session.awaitingTOTP ? totpCode : nil
        )
    }
}
