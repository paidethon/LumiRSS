import SwiftUI

/// 设置 tab: server/account info, appearance, reader defaults, cache
/// management, version, logout. Deliberately NOT a copy of the server
/// admin console — admin stays on the web.
struct SettingsView: View {
    @Environment(AppEnvironment.self) private var environment
    @AppStorage("readerFontSize") private var readerFontSize = 17
    @State private var cacheBytes: Int = 0
    @State private var confirmLogout = false
    @State private var confirmClearCache = false

    var body: some View {
        List {
            serverSection
            appearanceSection
            cacheSection
            aboutSection
            logoutSection
        }
        .navigationTitle(String(localized: "设置"))
        .task {
            cacheBytes = environment.cache.totalBytes()
        }
        .alert(String(localized: "退出登录"), isPresented: $confirmLogout) {
            Button(String(localized: "取消"), role: .cancel) {}
            Button(String(localized: "退出"), role: .destructive) {
                Task {
                    await environment.logout()
                }
            }
        } message: {
            Text(String(localized: "将撤销服务器会话并清除本机缓存。"))
        }
        .alert(String(localized: "清除缓存"), isPresented: $confirmClearCache) {
            Button(String(localized: "取消"), role: .cancel) {}
            Button(String(localized: "清除"), role: .destructive) {
                environment.clearCache()
                cacheBytes = environment.cache.totalBytes()
            }
        } message: {
            Text(String(localized: "仅清除本机缓存，不影响服务器数据。"))
        }
    }

    private var serverSection: some View {
        Section(String(localized: "服务器与账户")) {
            if let origin = environment.session.serverOrigin {
                LabeledContent(String(localized: "服务器"), value: origin.absoluteString)
            }
            if let account = environment.session.account {
                LabeledContent(String(localized: "账户"), value: account.username ?? "—")
                if let role = account.role {
                    LabeledContent(String(localized: "角色"), value: role)
                }
                if let expires = account.expiresAt {
                    LabeledContent(
                        String(localized: "会话有效期至"),
                        value: LumiDate.fullFormatter.string(from: expires)
                    )
                }
            }
            if let version = environment.session.serverVersion {
                LabeledContent(String(localized: "服务器版本"), value: version.version)
            }
        }
    }

    private var appearanceSection: some View {
        Section(String(localized: "阅读")) {
            Stepper(value: $readerFontSize, in: 14...24) {
                LabeledContent(String(localized: "正文字号"), value: "\(readerFontSize) pt")
            }
            .accessibilityLabel(String(localized: "正文字号"))
        }
    }

    private var cacheSection: some View {
        Section {
            LabeledContent(String(localized: "已用缓存"), value: ByteCountFormatter.string(fromByteCount: Int64(cacheBytes), countStyle: .file))
            Button(role: .destructive) {
                confirmClearCache = true
            } label: {
                Label(String(localized: "清除缓存"), systemImage: "trash")
            }
        } header: {
            Text(String(localized: "缓存"))
        } footer: {
            Text(String(localized: "缓存包含已加载的文章列表与正文（按服务器和账户隔离，不含图片）。清除后离线内容需要重新联网获取。"))
        }
    }

    private var aboutSection: some View {
        Section(String(localized: "关于")) {
            LabeledContent(String(localized: "客户端版本"), value: AppInfo.clientVersion)
            LabeledContent(String(localized: "最低兼容服务器"), value: "3.0.0")
        }
    }

    private var logoutSection: some View {
        Section {
            Button(role: .destructive) {
                confirmLogout = true
            } label: {
                Label(String(localized: "退出登录"), systemImage: "rectangle.portrait.and.arrow.right")
            }
        } footer: {
            Text(String(localized: "退出会撤销服务器会话并清除本机缓存；重新启动后需要重新登录。"))
        }
    }

}

enum AppInfo {
    static var clientVersion: String {
        let short = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(short) (\(build))"
    }
}
