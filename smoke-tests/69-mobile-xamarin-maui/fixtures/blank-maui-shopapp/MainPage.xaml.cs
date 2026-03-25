// ShopApp — .NET MAUI (C#)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Expected: agent adds OpenTelemetry.Exporter.OpenTelemetryProtocol
// and configures traces via MauiAppBuilder.

using System.Net.Http.Json;

namespace ShopApp;

public record Product(string Id, string Name, decimal Price, bool InStock);

public partial class MainPage : ContentPage
{
    private readonly HttpClient _http = new() { BaseAddress = new Uri("https://api.shopapp.io/v2/") };
    private readonly List<(Product product, int qty)> _cart = new();

    public MainPage() => InitializeComponent();

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        await LoadProductsAsync();
    }

    private async Task LoadProductsAsync()
    {
        LoadingIndicator.IsVisible = true;
        try
        {
            var products = await _http.GetFromJsonAsync<List<Product>>("products") ?? new();
            ProductList.ItemsSource = products;
        }
        finally
        {
            LoadingIndicator.IsVisible = false;
        }
    }

    private void OnAddToCart(object sender, EventArgs e)
    {
        if (sender is Button btn && btn.BindingContext is Product product)
        {
            var idx = _cart.FindIndex(i => i.product.Id == product.Id);
            if (idx >= 0)
                _cart[idx] = (_cart[idx].product, _cart[idx].qty + 1);
            else
                _cart.Add((product, 1));

            CartBadge.Text = _cart.Sum(i => i.qty).ToString();
            CartBadge.IsVisible = true;
        }
    }

    private async void OnCheckout(object sender, EventArgs e)
    {
        var total = _cart.Sum(i => i.product.Price * i.qty);
        var body  = new
        {
            customer_id = "maui_user",
            items = _cart.Select(i => new { product_id = i.product.Id, qty = i.qty }),
        };
        var resp = await _http.PostAsJsonAsync("orders", body);
        if (resp.IsSuccessStatusCode)
        {
            _cart.Clear();
            CartBadge.IsVisible = false;
            await DisplayAlert("Order Placed", $"Total: {total:C}", "OK");
        }
        else
        {
            await DisplayAlert("Error", "Checkout failed", "OK");
        }
    }
}
