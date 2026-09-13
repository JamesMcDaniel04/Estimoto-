import Flutter
import UIKit
import XCTest

class RunnerTests: XCTestCase {
  func testCustomerBundleIdentity() {
    XCTAssertEqual(Bundle.main.bundleIdentifier, "io.estimoto.plus")
    XCTAssertEqual(Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String, "Estimoto +")
  }
}
