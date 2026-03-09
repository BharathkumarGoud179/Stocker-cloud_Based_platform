from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal
from dotenv import load_dotenv
import uuid
import os

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ["SECRET_KEY"]
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")


STOCK_PRICES = {
    "AAPL": 185.0,
    "TSLA": 220.0,
    "AMZN": 175.0,
    "MSFT": 410.0,
    "GOOGL": 145.0
}

dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
   endpoint_url=DYNAMODB_ENDPOINT if DYNAMODB_ENDPOINT else None
    
)

users_table = dynamodb.Table("stocker_users")
portfolio_table = dynamodb.Table("stocker_portfolio")
transactions_table = dynamodb.Table("stocker_transactions")


def get_user_by_email(email):
    response = users_table.scan()
    for item in response.get("Items", []):
        if item.get("email") == email:
            return item
    return None


def get_user_portfolio_items(user_id):
    response = portfolio_table.scan()
    items = []
    for item in response.get("Items", []):
        if item.get("user_id") == user_id and int(item.get("quantity", 0)) > 0:
            items.append(item)
    return items


def get_user_transactions(user_id):
    response = transactions_table.scan()
    items = []
    for item in response.get("Items", []):
        if item.get("user_id") == user_id:
            items.append(item)
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return items


def update_portfolio(user_id, stock_symbol, quantity_change, price):
    portfolio_id = f"{user_id}#{stock_symbol}"

    try:
        response = portfolio_table.get_item(Key={"portfolio_id": portfolio_id})
        item = response.get("Item")

        if item:
            current_qty = int(item.get("quantity", 0))
            avg_buy_price = float(item.get("avg_buy_price", 0))
            new_qty = current_qty + quantity_change

            if new_qty < 0:
                return False, "Not enough shares to sell."

            if quantity_change > 0:
                total_old = current_qty * avg_buy_price
                total_new = quantity_change * price
                new_avg = (total_old + total_new) / new_qty if new_qty > 0 else 0
            else:
                new_avg = avg_buy_price

            portfolio_table.put_item(
                Item={
                    "portfolio_id": portfolio_id,
                    "user_id": user_id,
                    "stock_symbol": stock_symbol,
                    "quantity": new_qty,
                    "avg_buy_price": Decimal(str(round(new_avg, 2)))
                }
            )
        else:
            if quantity_change < 0:
                return False, "You do not own this stock."

            portfolio_table.put_item(
                Item={
                    "portfolio_id": portfolio_id,
                    "user_id": user_id,
                    "stock_symbol": stock_symbol,
                    "quantity": quantity_change,
                    "avg_buy_price": Decimal(str(price))
                }
            )

        return True, "Portfolio updated successfully."

    except ClientError as e:
        return False, str(e)


def save_transaction(user_id, stock_symbol, action, quantity, price):
    transaction_id = str(uuid.uuid4())

    transactions_table.put_item(
        Item={
            "transaction_id": transaction_id,
            "user_id": user_id,
            "stock_symbol": stock_symbol,
            "action": action,
            "quantity": quantity,
            "price": Decimal(str(price)),
            "total": Decimal(str(round(quantity * price, 2))),
            "timestamp": str(uuid.uuid1())
        }
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not name or not email or not password:
            error = "All fields are required."
        elif get_user_by_email(email):
            error = "Email already registered."
        else:
            user_id = str(uuid.uuid4())
            hashed_password = generate_password_hash(password)

            users_table.put_item(
                Item={
                    "user_id": user_id,
                    "name": name,
                    "email": email,
                    "password": hashed_password
                }
            )
            return redirect(url_for("login"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        user = get_user_by_email(email)

        if not user:
            error = "User not found."
        elif not check_password_hash(user["password"], password):
            error = "Invalid password."
        else:
            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    message = request.args.get("message", "")
    error = request.args.get("error", "")

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name"),
        stocks=STOCK_PRICES,
        message=message,
        error=error
    )


@app.route("/buy", methods=["POST"])
def buy_stock():
    if "user_id" not in session:
        return redirect(url_for("login"))

    stock_symbol = request.form.get("stock_symbol")
    quantity = request.form.get("quantity")

    if stock_symbol not in STOCK_PRICES:
        return redirect(url_for("dashboard", error="Invalid stock selected."))

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        return redirect(url_for("dashboard", error="Quantity must be a positive number."))

    price = STOCK_PRICES[stock_symbol]
    user_id = session["user_id"]

    success, msg = update_portfolio(user_id, stock_symbol, quantity, price)

    if success:
        save_transaction(user_id, stock_symbol, "BUY", quantity, price)
        return redirect(url_for("dashboard", message=f"Bought {quantity} shares of {stock_symbol}"))
    else:
        return redirect(url_for("dashboard", error=msg))


@app.route("/sell", methods=["POST"])
def sell_stock():
    if "user_id" not in session:
        return redirect(url_for("login"))

    stock_symbol = request.form.get("stock_symbol")
    quantity = request.form.get("quantity")

    if stock_symbol not in STOCK_PRICES:
        return redirect(url_for("dashboard", error="Invalid stock selected."))

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        return redirect(url_for("dashboard", error="Quantity must be a positive number."))

    price = STOCK_PRICES[stock_symbol]
    user_id = session["user_id"]

    success, msg = update_portfolio(user_id, stock_symbol, -quantity, price)

    if success:
        save_transaction(user_id, stock_symbol, "SELL", quantity, price)
        return redirect(url_for("dashboard", message=f"Sold {quantity} shares of {stock_symbol}"))
    else:
        return redirect(url_for("dashboard", error=msg))


@app.route("/portfolio")
def portfolio():
    if "user_id" not in session:
        return redirect(url_for("login"))

    items = get_user_portfolio_items(session["user_id"])
    portfolio_data = []
    total_value = 0

    for item in items:
        symbol = item["stock_symbol"]
        quantity = int(item["quantity"])
        avg_buy = float(item["avg_buy_price"])
        current_price = STOCK_PRICES.get(symbol, 0)
        current_value = quantity * current_price
        invested = quantity * avg_buy
        profit_loss = current_value - invested
        total_value += current_value

        portfolio_data.append({
            "stock_symbol": symbol,
            "quantity": quantity,
            "avg_buy_price": avg_buy,
            "current_price": current_price,
            "current_value": current_value,
            "profit_loss": profit_loss
        })

    return render_template("portfolio.html", portfolio_data=portfolio_data, total_value=total_value)


@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    transactions = get_user_transactions(session["user_id"])
    return render_template("history.html", transactions=transactions)


if __name__ == "__main__":
    app.run(debug=True)
