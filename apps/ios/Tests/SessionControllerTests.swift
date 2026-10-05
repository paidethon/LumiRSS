import XCTest
@testable import LumiRSS

@MainActor
final class SessionControllerTests: XCTestCase {
    func testEmptyStoreStartsUnconfigured() {
        let controller = SessionController(store: MemoryStore())
        XCTAssertEqual(controller.phase, .unconfigured)
        XCTAssertNil(controller.api)
    }

    func testStoredOriginStartsRestoring() throws {
        let store = MemoryStore()
        let origin = URL(string: "https://rss.example.com")!
        store.writeData(try JSONEncoder().encode(origin), forKey: "server.origin")
        let controller = SessionController(store: store)
        guard case .restoring(let restored) = controller.phase else {
            return XCTFail("expected .restoring, got \(controller.phase)")
        }
        XCTAssertEqual(restored, origin)
        XCTAssertNotNil(controller.api)
    }

    func testLogoutKeepsServerReturnsLoggedOut() async throws {
        let store = MemoryStore()
        let origin = URL(string: "https://rss.example.com")!
        store.writeData(try JSONEncoder().encode(origin), forKey: "server.origin")
        let controller = SessionController(store: store)
        await controller.logout()
        guard case .loggedOut = controller.phase else {
            return XCTFail("expected .loggedOut, got \(controller.phase)")
        }
        XCTAssertNil(store.readData(forKey: "session.cookie"))
        XCTAssertNil(store.readData(forKey: "session.account"))
    }

    func testForgetServerReturnsUnconfigured() throws {
        let store = MemoryStore()
        let origin = URL(string: "https://rss.example.com")!
        store.writeData(try JSONEncoder().encode(origin), forKey: "server.origin")
        let controller = SessionController(store: store)
        controller.forgetServer()
        XCTAssertEqual(controller.phase, .unconfigured)
        XCTAssertNil(store.readData(forKey: "server.origin"))
    }

    func testConfigureRejectsInvalidAddressWithoutProbe() async {
        let store = MemoryStore()
        let controller = SessionController(store: store)
        await controller.configureServer("ftp://bad")
        XCTAssertEqual(controller.phase, .unconfigured, "invalid input never stores a server")
        XCTAssertNotNil(controller.lastError)
    }
}
