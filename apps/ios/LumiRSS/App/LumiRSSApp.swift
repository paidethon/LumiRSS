import SwiftUI

@main
struct LumiRSSApp: App {
    @StateObject private var environment = AppEnvironment.live()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(environment)
                .tint(Color("LumiAccent"))
        }
    }
}
