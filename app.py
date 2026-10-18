
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

if "usd_per_unit" in raw_rates:
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
        amount = (
            float(order.get("qty", 0))
            * float(order.get("unit_price", 0))
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

        return date.astimezone(ZoneInfo("Asia/Kolkata"))

    except (ValueError, TypeError, AttributeError):
        return None


def answer_question(question):
    q = question.lower().strip()
    filtered = orders[:]

    # Filter by product name when one is mentioned.
    products = sorted(
        {
            str(o.get("product", ""))
            for o in orders
            if o.get("product")
        },
        key=len,
        reverse=True
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
        {
            str(o.get("region", ""))
            for o in orders
            if o.get("region")
        },
        key=len,
        reverse=True
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
        {
            str(o.get("customer", ""))
            for o in orders
            if o.get("customer")
        },
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

    # Filter by year and month using Asia/Kolkata dates.
    year_match = re.search(r"\b(20\d{2})\b", q)

    month_names = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12
    }

    month_number = None

    for month_name, number in month_names.items():
        if re.search(r"\b" + month_name + r"\b", q):
            month_number = number
            break

    if year_match or month_number:
        date_filtered = []

        for order in filtered:
            date = order_date(order)

            if date is None:
                continue

            if year_match and date.year != int(year_match.group(1)):
                continue

            if month_number and date.month != month_number:
                continue

            date_filtered.append(order)

        filtered = date_filtered

    # Status groups.
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

    # Detect product revenue ranking questions before general sales questions.
    product_ranking = (
        "product" in q
        or "which" in q
        or "earned the most" in q
        or "best-selling" in q
        or "best selling" in q
        or "highest-selling" in q
        or "highest selling" in q
        or "most popular" in q
        or "top product" in q
    )

    ranking_words = (
        "highest" in q
        or "most" in q
        or "top" in q
        or "best" in q
        or "earned" in q
        or "popular" in q
    )

    if product_ranking and ranking_words and any(
        word in q for word in [
            "revenue", "sales", "earned", "product",
            "selling", "popular"
        ]
    ):
        product_totals = defaultdict(float)

        for order in paid:
            name = order.get("product", "Unknown")
            product_totals[name] += amount_usd(order)

        if not product_totals:
            return "No matching paid orders found."

        best_product = max(
            product_totals,
            key=product_totals.get
        )

        return (
            f"{best_product}: "
            f"{product_totals[best_product]:.2f} USD"
        )

    # Highest-spending customer.
    if (
        "customer" in q
        and any(word in q for word in [
            "highest", "most", "spent", "spend", "top"
        ])
    ):
        customer_totals = defaultdict(float)

        for order in paid:
            name = order.get("customer", "Unknown")
            customer_totals[name] += amount_usd(order)

        if not customer_totals:
            return "No matching paid orders found."

        best_customer = max(
            customer_totals,
            key=customer_totals.get
        )

        return (
            f"{best_customer}: "
            f"{customer_totals[best_customer]:.2f} USD"
        )

    # Highest-revenue region.
    if (
        "region" in q
        and any(word in q for word in [
            "highest", "most", "top", "best"
        ])
    ):
        region_totals = defaultdict(float)

        for order in paid:
            name = order.get("region", "Unknown")
            region_totals[name] += amount_usd(order)

        if not region_totals:
            return "No matching paid orders found."

        best_region = max(region_totals, key=region_totals.get)

        return (
            f"{best_region}: "
            f"{region_totals[best_region]:.2f} USD"
        )

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

        if "customer" in q:
            return str(len({
                o.get("customer")
                for o in filtered
                if o.get("customer")
            }))

        if "product" in q:
            return str(len({
                o.get("product")
                for o in filtered
                if o.get("product")
            }))

        if any(word in q for word in [
            "unit", "quantity", "items"
        ]):
            return str(sum(
                int(o.get("qty", 0))
                for o in filtered
            ))

        if "order" in q:
            return str(len(filtered))

        return str(len(filtered))

    # Average order revenue.
    if "average" in q or "avg" in q:
        if not paid:
            return "0.00 USD"

        return f"{revenue / len(paid):.2f} USD"

    # General revenue and sales questions.
    if any(word in q for word in [
        "revenue", "sales", "sold", "amount", "total", "money"
    ]):
        return f"{revenue:.2f} USD"

    # General order summary.
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
        return jsonify({
            "answer": "Please provide a question."
        }), 400

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
