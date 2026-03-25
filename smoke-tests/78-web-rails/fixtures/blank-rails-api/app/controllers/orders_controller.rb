# Order API — Rails API (Ruby)
# No observability. Run `Observe this project.` to add OpenTelemetry.
class OrdersController < ApplicationController
  ORDERS = {}

  def health
    render json: { status: 'ok' }
  end

  def create
    items = params[:items] || []
    total = items.sum { |i| i[:price_usd].to_f * [i[:qty].to_i, 1].max }
    return render json: { error: 'total must be > 0' }, status: :bad_request if total <= 0

    order_id = "ORD-#{SecureRandom.hex(4).upcase}"
    order = { order_id:, customer_id: params[:customer_id] || 'anon',
              total_usd: total, status: 'confirmed', created_at: Time.now.iso8601 }
    ORDERS[order_id] = order
    render json: order, status: :created
  end

  def show
    order = ORDERS[params[:id]]
    return render json: { error: 'not found' }, status: :not_found unless order
    render json: order
  end
end
