// ShopApp — iOS (Swift + SwiftUI)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Expected: agent adds opentelemetry-swift or Elastic APM iOS agent.

import SwiftUI

struct Product: Identifiable, Codable {
    let id: String
    let name: String
    let price: Double
    let inStock: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, price
        case inStock = "in_stock"
    }
}

struct CartItem: Identifiable {
    let id = UUID()
    var product: Product
    var qty: Int
}

@MainActor
class ShopViewModel: ObservableObject {
    @Published var products: [Product] = []
    @Published var cart: [CartItem]    = []
    @Published var loading             = false
    @Published var orderId: String?    = nil
    @Published var error: String?      = nil

    private let apiBase = "https://api.shopapp.io/v2"

    func loadProducts() async {
        loading = true
        defer { loading = false }
        guard let url = URL(string: "\(apiBase)/products") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            products = try JSONDecoder().decode([Product].self, from: data)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func addToCart(_ product: Product) {
        if let idx = cart.firstIndex(where: { $0.product.id == product.id }) {
            cart[idx].qty += 1
        } else {
            cart.append(CartItem(product: product, qty: 1))
        }
    }

    var totalUSD: Double {
        cart.reduce(0) { $0 + $1.product.price * Double($1.qty) }
    }

    func checkout() async {
        loading = true
        defer { loading = false }
        guard let url = URL(string: "\(apiBase)/orders") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "customer_id": "ios_user",
            "items": cart.map { ["product_id": $0.product.id, "qty": $0.qty] }
        ]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse, http.statusCode == 201 {
                let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                orderId = json?["order_id"] as? String
                cart = []
            } else {
                error = "Checkout failed"
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct ContentView: View {
    @StateObject var vm = ShopViewModel()
    @State var screen: String = "home"

    var body: some View {
        NavigationStack {
            Group {
                if vm.loading {
                    ProgressView()
                } else if screen == "confirm" {
                    VStack(spacing: 16) {
                        Text("Order Confirmed!").font(.title)
                        Text("Order ID: \(vm.orderId ?? "—")")
                        Button("Continue Shopping") { screen = "home" }
                    }
                } else if screen == "cart" {
                    List(vm.cart) { item in
                        HStack {
                            Text("\(item.product.name) x\(item.qty)")
                            Spacer()
                            Text("$\(String(format: "%.2f", item.product.price * Double(item.qty)))")
                        }
                    }
                    .navigationTitle("Cart")
                    .toolbar {
                        Button("Place Order ($\(String(format: "%.2f", vm.totalUSD)))") {
                            Task {
                                await vm.checkout()
                                if vm.orderId != nil { screen = "confirm" }
                            }
                        }
                    }
                } else {
                    List(vm.products) { product in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(product.name).bold()
                                Text("$\(String(format: "%.2f", product.price))")
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("Add") { vm.addToCart(product) }
                                .disabled(!product.inStock)
                        }
                    }
                    .navigationTitle("ShopApp")
                    .toolbar {
                        if !vm.cart.isEmpty {
                            Button("Cart (\(vm.cart.count))") { screen = "cart" }
                        }
                    }
                }
            }
        }
        .task { await vm.loadProducts() }
        .alert("Error", isPresented: Binding(
            get: { vm.error != nil },
            set: { if !$0 { vm.error = nil } }
        )) {
            Button("OK") { vm.error = nil }
        } message: {
            Text(vm.error ?? "")
        }
    }
}
