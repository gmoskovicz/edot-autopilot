// swift-tools-version: 5.9
// ShopApp iOS — no OTel (fixture for 67-mobile-ios-swift eval)

import PackageDescription

let package = Package(
    name: "ShopApp",
    platforms: [.iOS(.v17)],
    products: [
        .executable(name: "ShopApp", targets: ["ShopApp"]),
    ],
    targets: [
        .executableTarget(
            name: "ShopApp",
            path: "ShopApp"
        ),
    ]
)
