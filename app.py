
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "all_orders.json"), encoding="utf-8-sig") as f:
    raw_orders = json.load(f)

with open(os.path.join(BASE_DIR, "rates.json"), encoding="utf-8-sig") as f:
    rates_data = json.load(f)

# Support both the API's original rate format and the saved rates.json format.
if "usd_per_unit" in rates_data:
    RATES = rates_data["usd_per_unit"]
else:
    RATES = rates_data

# Keep the latest version of each order ID.
latest_orders = {}

def parse_date(value):
    if not value:
        return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

for order in raw_orders:
    order_id = order["id"]
    if (
        order_id not in latest_orders
        or parse_date(order.get("updated_at")) >
        parse_date(latest_orders[order_id].get("updated_at"))
    ):
        latest_orders[order_id] = order

orders = list(latest_orders.values())

def amount_usd(order):
    currency = order.get("currency", "USD")
    amount = float(order.get("amount", 0))
    return amount * float(RATES.get(currency, 0))

def business_date(order):
    dt = parse_date(order.get("created_at"))
    return dt.astimezone(ZoneInfo("Asia/Kolkata"))

def answer_question(question):
    q = question.lower()
    filtered = orders[:]

    # Filter by product, region, or customer when named in the question.
    products = sorted(
        {str(o.get("product", "")) for o in orders},
        key=len, reverse=True
    )
    for product in products:
        if product.lower() in q:
            filtered = [
                o for o in filtered
                if str(o.get("product", "")).lower() == product.lower()
            ]
            break

    regions = sorted(
        {str(o.get("region", "")) for o in orders},
        key=len, reverse=True
    )
    for region in regions:
        if re.search(r"\b" + re.escape(region.lower()) + r"\b", q):
            filtered = [
                o for o in filtered
                if str(o.get("region", "")).lower() == region.lower()
            ]
            break

    customers = {str(o.get("customer", "")) for o in orders}
    for customer in customers:
        if customer.lower() in q:
            filtered = [
                o for o in filtered
                if str(o.get("customer", "")).lower() == customer.lower()
            ]
            break

    # Optional year and month filters.
    year_match = re.search(r"\b(20\d{2})\b", q)
    month_names = {
        "january": 1, "february": 2, "march": 3,
        "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9,
        "october": 10, "november": 11, "december": 12
    }
    selected_month = next(
        (number for name, number in month_names.items() if name in q),
        None
    )

    if year_match or selected_month:
        filtered = [
            o for o in filtered
            if (not year_match or business_date(o).year == int(year_match.group(1)))
            and (not selected_month or business_date(o).month == selected_month)
        ]

    paid = [o for o in filtered if o.get("status", "").lower() == "paid"]
    refunded = [
        o for o in filtered if o.get("status", "").lower() == "refunded"
    ]
    revenue = sum(amount_usd(o) for o in paid)
    refund_total = sum(amount_usd(o) for o in refunded)

    if any(word in q for word in ["refund", "refunded", "refunds"]):
        if "how many" in q or "number of" in q or "count" in q:
            return str(len(refunded))
        return f"{refund_total:.2f} USD"


	if any(word in q for word in ["how many", "number of", "count"]):
    		if "paid" in q:
        		return str(len(paid))
    		if "customer" in q:
        		return str(len({o.get("customer") for o in filtered}))
    		if "order" in q:
        		return str(len(filtered))
   		if "unit" in q or "quantity" in q or "items" in q:
        		return str(sum(int(o.get("qty", 0)) for o in filtered))
    		return str(len(filtered))


    if any(word in q for word in ["average", "avg"]):
        if not paid:
            return "0.00 USD"
        return f"{revenue / len(paid):.2f} USD"

    if any(word in q for word in [
    "top", "most popular", "best-selling", "best selling",
    "highest sales", "highest-selling", "highest selling",
    "most sales"
]):
        totals = defaultdict(float)
        for o in paid:
            key = o.get("product", "Unknown")
            totals[key] += amount_usd(o)
        if not totals:
            return "No matching paid orders found."
        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    if "customer" in q and any(w in q for w in ["spend", "spent", "purchase", "bought"]):
        totals = defaultdict(float)
        for o in paid:
            totals[o.get("customer", "Unknown")] += amount_usd(o)
        if not totals:
            return "No matching paid orders found."
        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    if any(word in q for word in ["revenue", "sales", "sold", "amount", "total", "money"]):
        return f"{revenue:.2f} USD"

    if "product" in q and not filtered:
        return "No matching orders found."

    return (
        f"Orders: {len(filtered)}; paid orders: {len(paid)}; "
        f"revenue: {revenue:.2f} USD; "
        f"refunded orders: {len(refunded)}; "
        f"refund total: {refund_total:.2f} USD"
    )

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Acme Appliances Ledger Agent is running",
        "orders_loaded": len(orders)
    })

@app.route("/", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    question = data.get("question")

    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Please provide a question."}), 400

    try:
        return jsonify({"answer": answer_question(question)})
    except Exception:
        app.logger.exception("Could not answer question")
        return jsonify({"answer": "Unable to answer this question."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
