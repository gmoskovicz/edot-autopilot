// ShopApp — Android (Kotlin + Jetpack Compose)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Expected: agent adds io.opentelemetry.android:android (OTel Android agent).

package com.example.shopapp

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.URL

data class Product(val id: String, val name: String, val price: Double, val inStock: Boolean)
data class CartItem(val product: Product, var qty: Int)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ShopAppTheme { ShopScreen() } }
    }
}

@Composable
fun ShopScreen() {
    val scope = rememberCoroutineScope()
    var products by remember { mutableStateOf<List<Product>>(emptyList()) }
    var cart     by remember { mutableStateOf<List<CartItem>>(emptyList()) }
    var loading  by remember { mutableStateOf(false) }
    var screen   by remember { mutableStateOf("home") }
    var orderId  by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        loading = true
        try {
            val json = URL("https://api.shopapp.io/v2/products").readText()
            // Parse JSON array (simplified)
            products = listOf(
                Product("p1", "Laptop Pro", 1999.0, true),
                Product("p2", "Headphones", 299.99, true),
                Product("p3", "Keyboard",  129.99, false),
            )
        } finally { loading = false }
    }

    fun addToCart(product: Product) {
        val idx = cart.indexOfFirst { it.product.id == product.id }
        cart = if (idx >= 0) cart.toMutableList().also { it[idx] = it[idx].copy(qty = it[idx].qty + 1) }
               else cart + CartItem(product, 1)
    }

    suspend fun checkout() {
        loading = true
        try {
            val json = JSONObject().apply {
                put("customer_id", "android_user")
                put("items", cart.map { mapOf("product_id" to it.product.id, "qty" to it.qty) })
            }
            // POST to API (simplified)
            orderId = "ORD-${System.currentTimeMillis()}"
            cart = emptyList()
            screen = "confirm"
        } finally { loading = false }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text(if (screen == "cart") "Cart" else "ShopApp") }) }
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when {
                loading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                screen == "confirm" -> Column(
                    Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Text("Order Confirmed!", style = MaterialTheme.typography.headlineMedium)
                    Text("Order ID: $orderId")
                    Button({ screen = "home" }) { Text("Continue Shopping") }
                }
                screen == "cart" -> Column {
                    LazyColumn(Modifier.weight(1f)) {
                        items(cart) { item ->
                            ListItem(
                                headlineContent = { Text("${item.product.name} x${item.qty}") },
                                trailingContent = { Text("$${String.format("%.2f", item.product.price * item.qty)}") }
                            )
                        }
                    }
                    val total = cart.sumOf { it.product.price * it.qty }
                    Button({ scope.launch { checkout() } }, Modifier.fillMaxWidth().padding(8.dp)) {
                        Text("Place Order (\$${String.format("%.2f", total)})")
                    }
                }
                else -> LazyColumn {
                    items(products) { product ->
                        ListItem(
                            headlineContent = { Text(product.name) },
                            supportingContent = { Text("$${String.format("%.2f", product.price)}") },
                            trailingContent = {
                                Button({ addToCart(product) }, enabled = product.inStock) {
                                    Text(if (product.inStock) "Add" else "OOS")
                                }
                            }
                        )
                    }
                    if (cart.isNotEmpty()) {
                        item {
                            Button({ screen = "cart" }, Modifier.fillMaxWidth().padding(8.dp)) {
                                Text("View Cart (${cart.size})")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ShopAppTheme(content: @Composable () -> Unit) {
    MaterialTheme(content = content)
}
