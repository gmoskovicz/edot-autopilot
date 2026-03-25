require 'sinatra'
require 'sinatra/json'
require 'json'
require 'securerandom'

# Subscription Management Service — Sinatra
#
# No observability. Run `Observe this project.` to add OpenTelemetry.
#
# Routes:
#   GET  /health                    — liveness probe
#   POST /subscriptions             — create subscription
#   GET  /subscriptions/:id         — get subscription
#   PUT  /subscriptions/:id/upgrade — upgrade plan

set :port, (ENV['PORT'] || 4567).to_i
set :bind, '0.0.0.0'

# ── In-memory store ────────────────────────────────────────────────────────────
SUBSCRIPTIONS = {}

PLAN_PRICES = {
  'free'       => 0.00,
  'pro'        => 79.00,
  'enterprise' => 499.00,
}.freeze

# ── Helpers ────────────────────────────────────────────────────────────────────
def call_stripe(amount_usd, customer_email)
  # Stub — replace with real Stripe::Charge.create in production
  sleep(0.05 + rand * 0.1)
  if amount_usd > 10_000
    { status: 'declined', reason: 'limit_exceeded' }
  else
    { status: 'charged', charge_id: "ch_#{SecureRandom.hex(8)}" }
  end
end

def validate_promo(code, plan)
  return 0.0 unless code
  discounts = { 'LAUNCH20' => 0.20, 'Q1SAVE' => 0.10, 'TEAM50' => 0.50 }
  (discounts[code] || 0.0) * PLAN_PRICES.fetch(plan, 0.0)
end

# ── Routes ─────────────────────────────────────────────────────────────────────
get '/health' do
  json status: 'ok'
end

post '/subscriptions' do
  body = JSON.parse(request.body.read, symbolize_names: true)

  customer_email = body[:customer_email] || 'anon@example.com'
  plan           = body[:plan] || 'free'
  promo_code     = body[:promo_code]

  unless PLAN_PRICES.key?(plan)
    status 400
    return json error: "unknown plan: #{plan}"
  end

  mrr          = PLAN_PRICES[plan]
  discount     = validate_promo(promo_code, plan)
  charge_amount = mrr - discount

  if charge_amount > 0
    payment = call_stripe(charge_amount, customer_email)
    unless payment[:status] == 'charged'
      status 402
      return json error: 'payment failed', reason: payment[:reason]
    end
  end

  sub_id = "SUB-#{SecureRandom.hex(4).upcase}"
  SUBSCRIPTIONS[sub_id] = {
    subscription_id: sub_id,
    customer_email:  customer_email,
    plan:            plan,
    mrr_usd:         charge_amount,
    status:          'active',
    charge_id:       charge_amount > 0 ? payment[:charge_id] : nil,
    created_at:      Time.now.iso8601,
  }

  puts "Subscription created: #{sub_id} #{customer_email} plan=#{plan} mrr=$#{charge_amount}"
  status 201
  json SUBSCRIPTIONS[sub_id]
end

get '/subscriptions/:id' do
  sub = SUBSCRIPTIONS[params[:id]]
  unless sub
    status 404
    return json error: 'not found'
  end
  json sub
end

put '/subscriptions/:id/upgrade' do
  sub = SUBSCRIPTIONS[params[:id]]
  unless sub
    status 404
    return json error: 'not found'
  end

  body     = JSON.parse(request.body.read, symbolize_names: true)
  new_plan = body[:plan]

  unless PLAN_PRICES.key?(new_plan)
    status 400
    return json error: "unknown plan: #{new_plan}"
  end

  new_mrr = PLAN_PRICES[new_plan]
  proration = new_mrr - sub[:mrr_usd]

  if proration > 0
    payment = call_stripe(proration, sub[:customer_email])
    unless payment[:status] == 'charged'
      status 402
      return json error: 'upgrade payment failed'
    end
  end

  SUBSCRIPTIONS[params[:id]][:plan]    = new_plan
  SUBSCRIPTIONS[params[:id]][:mrr_usd] = new_mrr
  puts "Subscription upgraded: #{params[:id]} -> #{new_plan}"
  json SUBSCRIPTIONS[params[:id]]
end
