
import json
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify

app = Flask(__name__)

with open("all_orders.json", "r", encoding="utf-8-sig") as file:
    raw_orders = json.load(file)

with open("rates.json", "r", encoding="utf-8-sig") as file:
    raw_rates = json.load(file)

if isinstance(raw_rates, dict) and "usd_per_unit" in raw_rates:
    rates = raw_rates["usd_per_unit"]
else:
    rates = raw_rates

# Keep the latest version of each order.
latest_orders = {}

for order in raw_orders:
    order_id = order.get("id")

    if order_id not in latest_orders:
        latest_orders[order_id] = order
    else:
        old_date = latest_orders[order_id].get("updated_at", "")
        new_date = order.get("updated_at", "")

        if new_date > old_date:
            latest_orders[order_id] = order

orders = list(latest_orders.values())


def amount_usd(order):
    amount = order.get("amount")

    if amount is None:
        amount = float(order.get("qty", 0)) * float(
            order.get("unit_price", 0)
        )

    currency = order.get("currency", "USD")
    rate = float(rates.get(currency, 1))

    return float(amount) * rate


def order_date(order):
    value = order.get("created_at", "")

    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if date.tzinfo is None:
            date = date.replace(tzinfo=ZoneInfo("UTC"))

        return date.astimezone(
            ZoneInfo("Asia/Kolkata")
        )
    except (ValueError, TypeError):
        return None


def answer_question(question):
    q = question.lower()
    filtered = orders[:]

    # Filter by product.
    products = sorted(
        {str(o.get("product", "")) for o in orders if o.get("product")}
    )

    for product in products:
        if product.lower() in q:
            filtered = [
                o for o in filtered
                if str(o.get("product", "")).lower() == product.lower()
            ]
            break

    # Filter by region.
    regions = sorted(
        {str(o.get("region", "")) for o in orders if o.get("region")}
    )

    for region in regions:
        if re.search(r"\b" + re.escape(region.lower()) + r"\b", q):
            filtered = [
                o for o in filtered
                if str(o.get("region", "")).lower() == region.lower()
            ]
            break

    # Filter by customer.
    customers = sorted(
        {str(o.get("customer", "")) for o in orders if o.get("customer")},
        key=len,
        reverse=True
    )

    for customer in customers:
        if customer.lower() in q:
            filtered = [
                o for o in filtered
                if str(o.get("customer", "")).lower() == customer.lower()
            ]
            break

    # Filter by year and month.
    year_match = re.search(r"\b(20\d{2})\b", q)
    month_names = {
        "january": 1, "february": 2, "march": 3,
        "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9,
        "october": 10, "november": 11, "december": 12
    }

    month_number = None

    for month_name, number in month_names.items():
        if month_name in q:
            month_number = number
            break

    if year_match or month_number:
        selected = []

        for order in filtered:
            date = order_date(order)

            if date is None:
                continue

            if year_match and date.year != int(year_match.group(1)):
                continue

            if month_number and date.month != month_number:
                continue

            selected.append(order)

        filtered = selected

    paid = [
        o for o in filtered
        if str(o.get("status", "")).lower() == "paid"
    ]

    refunded = [
        o for o in filtered
        if str(o.get("status", "")).lower() == "refunded"
    ]

    revenue = sum(amount_usd(o) for o in paid)
    refund_total = sum(amount_usd(o) for o in refunded)

    # Product sales ranking.
    if any(word in q for word in [
        "highest sales", "most sales", "top product",
        "best-selling", "best selling", "most popular",
        "highest-selling", "highest selling"
    ]):
        totals = defaultdict(float)

        for order in paid:
            totals[order.get("product", "Unknown")] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    # Refund questions.
    if any(word in q for word in ["refund", "refunded", "refunds"]):
        if any(word in q for word in [
            "how many", "number of", "count"
        ]):
            return str(len(refunded))

        return f"{refund_total:.2f} USD"

    # Count questions.
    if any(word in q for word in [
        "how many", "number of", "count"
    ]):
        if "paid" in q:
            return str(len(paid))

        if "refunded" in q:
            return str(len(refunded))

        if "customer" in q:
            return str(len({
                o.get("customer") for o in filtered
                if o.get("customer")
            }))

        if "product" in q:
            return str(len({
                o.get("product") for o in filtered
                if o.get("product")
            }))

        if any(word in q for word in [
            "unit", "quantity", "items"
        ]):
            return str(sum(int(o.get("qty", 0)) for o in filtered))

        if "order" in q:
            return str(len(filtered))

        return str(len(filtered))

    # Average questions.
    if "average" in q or "avg" in q:
        if not paid:
            return "0.00 USD"

        if "order" in q:
            return f"{revenue / len(paid):.2f} USD"

        return f"{revenue / len(paid):.2f} USD"

    # Highest-spending customer.
    if "customer" in q and any(word in q for word in [
        "spend", "spent", "purchase", "bought", "highest"
    ]):
        totals = defaultdict(float)

        for order in paid:
            totals[order.get("customer", "Unknown")] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    # Highest-revenue region.
    if "region" in q and any(word in q for word in [
        "highest", "most", "top", "best"
    ]):
        totals = defaultdict(float)

        for order in paid:
            totals[order.get("region", "Unknown")] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    # Revenue and sales questions.
    if any(word in q for word in [
        "revenue", "sales", "sold", "amount", "total", "money"
    ]):
        return f"{revenue:.2f} USD"

    # General summary.
    if not filtered:
        return "No matching orders found."

    return (
        f"Orders: {len(filtered)}; "
        f"paid orders: {len(paid)}; "
        f"revenue: {revenue:.2f} USD; "
        f"refunded orders: {len(refunded)}; "
        f"refund total: {refund_total:.2f} USD"
    )


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return jsonify({
            "message": "Ledger Agent is running",
            "orders_loaded": len(orders)
        })

    data = request.get_json(silent=True) or {}
    question = data.get("question", "")

    if not isinstance(question, str) or not question.strip():
        return jsonify({"answer": "Please provide a question."}), 400

    try:
        answer = answer_question(question)
        return jsonify({"answer": answer})
    except Exception:
        app.logger.exception("Failed to answer question")
        return jsonify({
            "answer": "Unable to process this question."
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
