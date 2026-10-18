
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify

app = Flask(__name__)

BUSINESS_TZ = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

with open("all_orders.json", "r", encoding="utf-8-sig") as file:
    raw_orders = json.load(file)

with open("rates.json", "r", encoding="utf-8-sig") as file:
    raw_rates = json.load(file)

if "usd_per_unit" in raw_rates:
    rates = raw_rates["usd_per_unit"]
else:
    rates = raw_rates


def parse_datetime(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)

        return result.astimezone(UTC)

    except (ValueError, TypeError, OverflowError):
        return None


# Keep the most recently updated version of each order.
latest_orders = {}

for order in raw_orders:
    order_id = order.get("id")

    if order_id is None:
        continue

    if order_id not in latest_orders:
        latest_orders[order_id] = order
        continue

    old_time = parse_datetime(
        latest_orders[order_id].get("updated_at")
    )
    new_time = parse_datetime(order.get("updated_at"))

    if new_time is not None:
        if old_time is None or new_time > old_time:
            latest_orders[order_id] = order

orders = list(latest_orders.values())


def amount_usd(order):
    amount = order.get("amount")

    if amount is None:
        amount = (
            float(order.get("qty", 0))
            * float(order.get("unit_price", 0))
        )

    currency = str(order.get("currency", "USD")).upper()

    if currency not in rates:
        raise ValueError("Unknown currency: " + currency)

    return float(amount) * float(rates[currency])


def business_date(order):
    date = parse_datetime(order.get("created_at"))

    if date is None:
        return None

    return date.astimezone(BUSINESS_TZ)


def answer_question(question):
    q = question.lower().strip()
    filtered = orders[:]

    # Filter by a named product.
    products = sorted(
        {
            str(order.get("product", ""))
            for order in orders
            if order.get("product")
        },
        key=len,
        reverse=True
    )

    for product in products:
        if product.lower() in q:
            filtered = [
                order for order in filtered
                if str(order.get("product", "")).lower()
                == product.lower()
            ]
            break

    # Filter by region.
    regions = sorted(
        {
            str(order.get("region", ""))
            for order in orders
            if order.get("region")
        },
        key=len,
        reverse=True
    )

    for region in regions:
        if re.search(r"\b" + re.escape(region.lower()) + r"\b", q):
            filtered = [
                order for order in filtered
                if str(order.get("region", "")).lower()
                == region.lower()
            ]
            break

    # Filter by customer.
    customers = sorted(
        {
            str(order.get("customer", ""))
            for order in orders
            if order.get("customer")
        },
        key=len,
        reverse=True
    )

    for customer in customers:
        if customer.lower() in q:
            filtered = [
                order for order in filtered
                if str(order.get("customer", "")).lower()
                == customer.lower()
            ]
            break

    # Filter by year and month using business dates.
    year_match = re.search(r"\b(20\d{2})\b", q)

    months = {
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

    for month_name, number in months.items():
        if re.search(r"\b" + month_name + r"\b", q):
            month_number = number
            break

    if year_match or month_number:
        selected = []

        for order in filtered:
            date = business_date(order)

            if date is None:
                continue

            if year_match and date.year != int(year_match.group(1)):
                continue

            if month_number and date.month != month_number:
                continue

            selected.append(order)

        filtered = selected

    # Only paid orders contribute to revenue.
    paid = [
        order for order in filtered
        if str(order.get("status", "")).lower() == "paid"
    ]

    refunded = [
        order for order in filtered
        if str(order.get("status", "")).lower() == "refunded"
    ]

    revenue = sum(amount_usd(order) for order in paid)
    refund_total = sum(amount_usd(order) for order in refunded)

    # Detect product revenue ranking questions first.
    ranking_words = [
        "top", "highest", "most", "best", "earned",
        "best-selling", "best selling",
        "top-selling", "top selling",
        "highest-selling", "highest selling",
        "most popular"
    ]

    ranking_question = any(word in q for word in ranking_words)

    product_question = (
        "product" in q
        or "item" in q
        or "which" in q
    )

    revenue_question = any(word in q for word in [
        "revenue", "sales", "selling", "sold",
        "earned", "amount"
    ])

    if (
        ranking_question
        and product_question
        and revenue_question
    ):
        totals = defaultdict(float)

        for order in paid:
            name = order.get("product", "Unknown")
            totals[name] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        best_product = max(totals, key=totals.get)

        return best_product

    # Highest-spending customer.
    if (
        "customer" in q
        and any(word in q for word in [
            "highest", "most", "top", "spent", "spend"
        ])
    ):
        totals = defaultdict(float)

        for order in paid:
            totals[order.get("customer", "Unknown")] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    # Highest-revenue region.
    if (
        "region" in q
        and any(word in q for word in [
            "highest", "most", "top", "best"
        ])
    ):
        totals = defaultdict(float)

        for order in paid:
            totals[order.get("region", "Unknown")] += amount_usd(order)

        if not totals:
            return "No matching paid orders found."

        name = max(totals, key=totals.get)
        return f"{name}: {totals[name]:.2f} USD"

    # Refund questions.
    if any(word in q for word in [
        "refund", "refunded", "refunds"
    ]):
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
                order.get("customer")
                for order in filtered
                if order.get("customer")
            }))

        if "product" in q:
            return str(len({
                order.get("product")
                for order in filtered
                if order.get("product")
            }))

        if any(word in q for word in [
            "unit", "quantity", "items"
        ]):
            return str(sum(
                int(order.get("qty", 0))
                for order in filtered
            ))

        if "order" in q:
            return str(len(filtered))

        return str(len(filtered))

    # Average revenue per paid order.
    if "average" in q or "avg" in q:
        if not paid:
            return "0.00 USD"

        return f"{revenue / len(paid):.2f} USD"

    # Total revenue questions.
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
        return jsonify({
            "answer": "Please provide a question."
        }), 400

    try:
        return jsonify({
            "answer": answer_question(question)
        })
    except Exception:
        app.logger.exception("Error answering question")
        return jsonify({
            "answer": "Unable to process this question."
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
