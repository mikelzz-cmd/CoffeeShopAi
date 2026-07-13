from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
import mysql.connector.pooling
from dotenv import load_dotenv
import os
import time
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_wtf import CSRFProtect


load_dotenv()


from google import genai

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

app = Flask(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Add a long random value to your .env file, "
        "e.g. SECRET_KEY=your-random-string-here"
    )
app.secret_key = SECRET_KEY

csrf = CSRFProtect(app)

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def make_unique_filename(original_filename):
    ext = secure_filename(original_filename).rsplit(".", 1)[1].lower()
    return f"{uuid.uuid4().hex}.{ext}"


def verify_password(stored_password, provided_password):
    try:
        if check_password_hash(stored_password, provided_password):
            return True
    except Exception:
        pass
    return stored_password == provided_password


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        if not session.get("is_admin"):
            flash("Admins only.")
            return redirect(url_for("dashboard"))

        return view_func(*args, **kwargs)

    return wrapper


db_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="coffee_pool",
    pool_size=10,
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "coffee_shop")
)


def get_db_connection():
    return db_pool.get_connection()


@app.context_processor
def inject_cart_count():

    cart = session.get("cart", [])

    return dict(
        cart_count=sum(item.get("quantity", 0) for item in cart)
    )


# ==========================================
# IMAGE URL HELPER  (added)
# handles both locally-uploaded images (relative paths like
# "uploads/xyz.jpg", need /static/ prefix) and full external URLs
# (like the seeded Unsplash photos, used as-is)
# ==========================================
@app.template_global()
def image_url(path):

    if not path:
        return ""

    if path.startswith("http://") or path.startswith("https://"):
        return path

    return url_for("static", filename=path)



def create_notification(user_id, message, link=None):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO notifications (user_id, message, link)
        VALUES (%s, %s, %s)
    """, (user_id, message, link))

    conn.commit()

    cursor.close()
    conn.close()


@app.context_processor
def inject_notifications():

    if "user_id" not in session:
        return dict(unread_notifications=0, recent_notifications=[])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT COUNT(*) AS total FROM notifications WHERE user_id=%s AND is_read=0",
        (session["user_id"],)
    )
    unread = cursor.fetchone()["total"]

    cursor.execute(
        "SELECT * FROM notifications WHERE user_id=%s ORDER BY id DESC LIMIT 6",
        (session["user_id"],)
    )
    recent = cursor.fetchall()

    cursor.close()
    conn.close()

    return dict(unread_notifications=unread, recent_notifications=recent)


@app.route("/")
def home():

    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form["fullname"]
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for("register"))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM users WHERE username=%s",
            (username,)
        )

        if cursor.fetchone():
            cursor.close()
            conn.close()

            flash("Username already exists!")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        cursor.execute("""
            INSERT INTO users
            (
                fullname,
                username,
                password
            )
            VALUES
            (
                %s,
                %s,
                %s
            )
        """, (
            fullname,
            username,
            hashed_password
        ))

        conn.commit()

        cursor.close()
        conn.close()

        flash("Registration Successful!")

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():


    next_url = request.values.get("next")

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM users
            WHERE username=%s
        """, (
            username,
        ))

        user = cursor.fetchone()

        if user and verify_password(user["password"], password):

            if not user["password"].startswith(("pbkdf2:", "scrypt:")):
                upgrade_cursor = conn.cursor()
                upgrade_cursor.execute(
                    "UPDATE users SET password=%s WHERE id=%s",
                    (generate_password_hash(password), user["id"])
                )
                conn.commit()
                upgrade_cursor.close()

        else:
            user = None

        cursor.close()
        conn.close()

        if user:

            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["profile_image"] = user.get("profile_image")
            session["is_admin"] = bool(user.get("is_admin"))

            if "cart" not in session:
                session["cart"] = []

            flash(f"Welcome {user['fullname']}!")

            return redirect(next_url or url_for("dashboard"))

        flash("Invalid username or password!")

        return redirect(url_for("login", next=next_url) if next_url else url_for("login"))

    return render_template("login.html", next=next_url)


@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully!")

    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            product_name,
            category,
            description,
            price,
            image
        FROM products
        ORDER BY id ASC
    """)

    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "dashboard.html",
        fullname=session.get("fullname"),
        products=products
    )


@app.route("/cart")
def cart():

    cart = session.get("cart", [])

    total = sum(
        item["price"] * item["quantity"]
        for item in cart
    )

    return render_template(
        "cart.html",
        cart=cart,
        total=total
    )


@app.route("/add_to_cart/<int:product_id>")
def add_to_cart(product_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE id=%s",
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!")
        return redirect(url_for("dashboard"))

    cart = session.get("cart", [])

    found = False

    for item in cart:

        if item["id"] == product["id"]:
            item["quantity"] += 1
            found = True
            break

    if not found:

        cart.append({
            "id": product["id"],
            "name": product["product_name"],
            "price": float(product["price"]),
            "image": product["image"],
            "quantity": 1
        })

    session["cart"] = cart
    session.modified = True

    flash(f"{product['product_name']} added to cart!")

    return redirect(url_for("cart"))

@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):



    cart = session.get("cart", [])

    cart = [
        item
        for item in cart
        if item["id"] != product_id
    ]

    session["cart"] = cart
    session.modified = True

    flash("Item removed from cart!")

    return redirect(url_for("cart"))


@app.route("/increase_cart_item/<int:product_id>")
def increase_cart_item(product_id):

    cart = session.get("cart", [])

    for item in cart:
        if item["id"] == product_id:
            item["quantity"] += 1
            break

    session["cart"] = cart
    session.modified = True

    return redirect(url_for("cart"))

@app.route("/decrease_cart_item/<int:product_id>")
def decrease_cart_item(product_id):

    cart = session.get("cart", [])

    for item in cart:
        if item["id"] == product_id:
            if item["quantity"] > 1:
                item["quantity"] -= 1
            break

    session["cart"] = cart
    session.modified = True

    return redirect(url_for("cart"))

@app.route("/clear_cart")
def clear_cart():

    session["cart"] = []
    session.modified = True

    flash("Cart cleared!")

    return redirect(url_for("cart"))

@app.route("/checkout")
def checkout():

    if "user_id" not in session:
        flash("Please log in to complete your order.")
        return redirect(url_for("login", next=url_for("checkout")))

    cart = session.get("cart", [])

    if not cart:
        flash("Your cart is empty!")
        return redirect(url_for("cart"))

    total = sum(item["price"] * item["quantity"] for item in cart)

    return render_template(
        "checkout.html",
        cart=cart,
        total=total
    )

@app.route("/place_order", methods=["POST"])
def place_order():

    print("PLACE ORDER ROUTE WORKING")

    if "user_id" not in session:
        return redirect(url_for("login"))

    cart = session.get("cart", [])

    if not cart:
        flash("Your cart is empty!")
        return redirect(url_for("cart"))

    fullname = request.form.get("fullname", "")
    contact = request.form.get("contact", "")
    address = request.form.get("address", "")
    order_type = request.form.get("order_type", "Dine In")
    payment_method = request.form.get("payment_method", "Cash")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    for item in cart:

        cursor.execute("SELECT stock, product_name FROM products WHERE id=%s", (item["id"],))
        row = cursor.fetchone()

        if row is None or row["stock"] < item["quantity"]:
            cursor.close()
            conn.close()
            flash(f"Sorry, '{item['name']}' doesn't have enough stock left.")
            return redirect(url_for("cart"))

    cursor.close()
    cursor = conn.cursor()

    try:

        order_ids = []

        for item in cart:

            total = item["price"] * item["quantity"]

            cursor.execute("""
                UPDATE products
                SET stock = stock - %s
                WHERE id = %s
            """, (item["quantity"], item["id"]))

            cursor.execute("""
                INSERT INTO orders
                (
                    user_id,
                    customer_name,
                    contact_number,
                    address,
                    order_type,
                    payment_method,
                    product_name,
                    quantity,
                    price,
                    total,
                    status
                )
                VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                session["user_id"],
                fullname,
                contact,
                address,
                order_type,
                payment_method,
                item["name"],
                item["quantity"],
                item["price"],
                total,
                "Pending"
            ))

            order_ids.append(cursor.lastrowid)

        conn.commit()

        session["cart"] = []
        session.modified = True

        flash("Order placed successfully!")


        item_count = len(cart)
        grand_total = sum(item["price"] * item["quantity"] for item in cart)
        create_notification(
            session["user_id"],
            f"Order placed! {item_count} item(s) totaling ₱{grand_total:.2f}.",
            link=url_for("orders")
        )

        # (added) notify every admin account about this new order
        admin_conn = get_db_connection()
        admin_cursor = admin_conn.cursor(dictionary=True)
        admin_cursor.execute("SELECT id FROM users WHERE is_admin=1")
        admin_ids = [row["id"] for row in admin_cursor.fetchall()]
        admin_cursor.close()
        admin_conn.close()

        customer_name = fullname or session.get("fullname") or "A customer"

        for admin_id in admin_ids:
            create_notification(
                admin_id,
                f"New order from {customer_name}: {item_count} item(s) totaling ₱{grand_total:.2f}.",
                link=url_for("admin_orders")
            )

        return redirect(url_for("receipt", order_ids=",".join(str(i) for i in order_ids)))

    except Exception as e:

        conn.rollback()
        print(e)
        flash(str(e))

        return redirect(url_for("checkout"))

    finally:

        cursor.close()
        conn.close()


@app.route("/receipt/<order_ids>")
def receipt(order_ids):

    if "user_id" not in session:
        return redirect(url_for("login"))

    id_list = [int(i) for i in order_ids.split(",") if i.strip().isdigit()]

    if not id_list:
        flash("Order not found!")
        return redirect(url_for("orders"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    placeholders = ",".join(["%s"] * len(id_list))

    cursor.execute(
        f"SELECT * FROM orders WHERE id IN ({placeholders})",
        tuple(id_list)
    )

    receipt_orders = cursor.fetchall()

    cursor.close()
    conn.close()

    if not receipt_orders:
        flash("Order not found!")
        return redirect(url_for("orders"))

    grand_total = sum(float(o["total"]) for o in receipt_orders)

    return render_template(
        "receipt.html",
        orders=receipt_orders,
        grand_total=grand_total,
        order_ids=order_ids
    )


@app.route("/orders")
def orders():

    if "user_id" not in session:
        return redirect(url_for("login"))


    status_filter = request.args.get("status", "All")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if status_filter in ["Pending", "Preparing", "Completed", "Cancelled"]:
        cursor.execute("""
            SELECT *
            FROM orders
            WHERE user_id=%s AND status=%s
            ORDER BY id DESC
        """, (session["user_id"], status_filter))
    else:
        status_filter = "All"
        cursor.execute("""
            SELECT *
            FROM orders
            WHERE user_id=%s
            ORDER BY id DESC
        """, (session["user_id"],))

    orders = cursor.fetchall()


    grouped_orders = []

    for o in orders:
        ts = o.get("timestamp")
        if  grouped_orders and ts is not None and grouped_orders[-1]["timestamp"] == ts:
            grouped_orders[-1]["orders"].append(o)
            grouped_orders[-1]["total"] += float(o["total"])
            grouped_orders[-1]["ids"].append(o["id"])
        else:
            grouped_orders.append({
                "timestamp": ts,
                "order_type": o.get("order_type"),
                "payment_method": o.get("payment_method"),
                "orders": [o],
                "total": float(o["total"]),
                "ids": [o["id"]]
            })


    cursor.execute("""
        SELECT status, COUNT(*) AS total
        FROM orders
        WHERE user_id=%s
        GROUP BY status
    """, (session["user_id"],))

    status_counts = {row["status"]: row["total"] for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    return render_template(
        "orders.html",
        grouped_orders=grouped_orders,
        status_filter=status_filter,
        status_counts=status_counts
    )


@app.route("/update_order_quantity/<int:order_id>/<action>")
def update_order_quantity(order_id, action):

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM orders WHERE id=%s AND user_id=%s",
        (order_id, session["user_id"])
    )

    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        flash("Order not found!")
        return redirect(url_for("orders"))

    if order["status"] != "Pending":
        cursor.close()
        conn.close()
        flash("Only pending orders can be changed.")
        return redirect(url_for("orders"))

    quantity = order["quantity"]

    if action == "increase":
        quantity += 1
    elif action == "decrease":
        quantity -= 1

    if quantity < 1:
        cursor.close()
        conn.close()
        flash("Quantity can't go below 1. Cancel the order instead.")
        return redirect(url_for("orders"))

    new_total = float(order["price"]) * quantity

    cursor.execute("""
        UPDATE orders
        SET quantity=%s, total=%s
        WHERE id=%s
    """, (quantity, new_total, order_id))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Order quantity updated!")

    return redirect(url_for("orders"))


@app.route("/cancel_order/<int:order_id>")
def cancel_order(order_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM orders WHERE id=%s AND user_id=%s",
        (order_id, session["user_id"])
    )

    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        flash("Order not found!")
        return redirect(url_for("orders"))

    if order["status"] != "Pending":
        cursor.close()
        conn.close()
        flash("This order can no longer be cancelled.")
        return redirect(url_for("orders"))

    cursor.execute("""
        UPDATE orders
        SET status='Cancelled'
        WHERE id=%s
    """, (order_id,))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Order cancelled.")

    return redirect(url_for("orders"))


@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            fullname,
            username,
            profile_image
        FROM users
        WHERE id=%s
    """, (session["user_id"],))

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "profile.html",
        user=user,
        fullname=session.get("fullname"),
        profile_image=session.get("profile_image")
    )


@app.route("/update_profile", methods=["POST"])
def update_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    fullname = request.form["fullname"]
    username = request.form["username"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE username=%s AND id!=%s",
        (username, session["user_id"])
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        flash("That username is already taken. Please choose another.")
        return redirect(url_for("profile"))

    cursor.execute("""
        UPDATE users
        SET
            fullname=%s,
            username=%s
        WHERE id=%s
    """, (
        fullname,
        username,
        session["user_id"]
    ))

    conn.commit()

    cursor.close()
    conn.close()

    session["fullname"] = fullname

    flash("Profile updated successfully!")

    return redirect(url_for("profile"))


@app.route("/settings")
def settings():

    if "user_id" not in session:
        return redirect(url_for("login"))


    return render_template(
        "settings.html",
        fullname=session.get("fullname"),
        profile_image=session.get("profile_image")
    )

@app.route("/change_password", methods=["POST"])
def change_password():

    if "user_id" not in session:
        return redirect(url_for("login"))

    current_password = request.form["current_password"]
    new_password = request.form["new_password"]
    confirm_password = request.form["confirm_password"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT password FROM users WHERE id=%s",
        (session["user_id"],)
    )

    user = cursor.fetchone()

    if not user:

        cursor.close()
        conn.close()

        flash("User not found!")

        return redirect(url_for("settings"))

    if not verify_password(user["password"], current_password):

        cursor.close()
        conn.close()

        flash("Current password is incorrect!")

        return redirect(url_for("settings"))

    if new_password != confirm_password:

        cursor.close()
        conn.close()

        flash("New passwords do not match!")

        return redirect(url_for("settings"))

    cursor.execute("""
        UPDATE users
        SET password=%s
        WHERE id=%s
    """, (
        generate_password_hash(new_password),
        session["user_id"]
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Password changed successfully!")

    return redirect(url_for("profile"))


@app.route("/upload_profile", methods=["POST"])
def upload_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if "profile" not in request.files:

        flash("Please select an image.")

        return redirect(url_for("profile"))

    file = request.files["profile"]

    if file.filename == "":

        flash("Please select an image.")

        return redirect(url_for("profile"))

    if not allowed_file(file.filename):

        flash("Invalid file type. Please upload a PNG, JPG, JPEG, GIF, or WEBP image.")

        return redirect(url_for("profile"))

    filename = make_unique_filename(file.filename)

    filepath = os.path.join(UPLOAD_FOLDER, filename)

    file.save(filepath)

    image_path = f"uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET profile_image=%s
        WHERE id=%s
    """, (
        image_path,
        session["user_id"]
    ))

    conn.commit()

    cursor.close()
    conn.close()

    session["profile_image"] = image_path

    flash("Profile picture updated successfully!")

    return redirect(url_for("profile"))


@app.route("/notifications")
def notifications():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM notifications WHERE user_id=%s ORDER BY id DESC",
        (session["user_id"],)
    )
    all_notifications = cursor.fetchall()

    update_cursor = conn.cursor()
    update_cursor.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=%s AND is_read=0",
        (session["user_id"],)
    )
    conn.commit()

    update_cursor.close()
    cursor.close()
    conn.close()

    return render_template("notifications.html", all_notifications=all_notifications)


def get_menu_context():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            product_name,
            category,
            price,
            description,
            ingredients,
            calories,
            caffeine,
            sweetness,
            bestseller
        FROM products
        ORDER BY category, product_name
    """)

    products = cursor.fetchall()

    cursor.close()
    conn.close()

    if not products:
        return "Walang available na menu items ngayon."

    lines = []

    for p in products:
        line = f"- {p['product_name']} ({p['category']}) - ₱{p['price']}"

        if p.get("description"):
            line += f"\n  Description: {p['description']}"

        if p.get("ingredients"):
            line += f"\n  Ingredients: {p['ingredients']}"

        if p.get("calories"):
            line += f"\n  Calories: {p['calories']}"

        if p.get("bestseller"):
            line += "\n  ⭐ Bestseller"

        lines.append(line)

    return "\n".join(lines)


@app.route("/chatbot")
def chatbot():

    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("chatbot.html")


@app.route("/chat", methods=["POST"])
@csrf.exempt
def chat():

    if "user_id" not in session:
        return jsonify({
            "reply": "Please login first."
        })

    message = request.form.get("message", "").strip()

    if not message:
        return jsonify({
            "reply": "Please enter a message."
        })

    now = time.time()
    last_time = session.get("last_chat_time", 0)

    if now - last_time < 2:
        return jsonify({
            "reply": "Sandali lang po! Ang bilis niyong mag-type 😅 Mag-antay muna ng ilang segundo."
        })

    session["last_chat_time"] = now

    history = session.get("chat_history", [])

    history_text = ""
    if history:
        history_text = "\n\nPrevious conversation (for context only):\n" + "\n".join(
            f"Customer: {h['user']}\nCoffeeBot: {h['bot']}"
            for h in history[-5:]
        )

    menu_context = get_menu_context()

    prompt = f"""
You are CoffeeBot, the official AI assistant of Tara Kape Coffee Shop.

Here is the CURRENT MENU from our database. Use ONLY this information
when answering questions about menu items, prices, or ingredients.
Do not invent items or ingredients that are not listed here.

MENU:
{menu_context}
{history_text}

Rules:
- Only answer questions related to Tara Kape Coffee Shop.
- Use the previous conversation above for context (e.g. "yung una mong sinabi").
- If asked "ano menu niyo" or similar, list the item names and prices, grouped by category.
- If asked about ingredients of a specific item, quote the ingredients exactly as listed above.
- If the item is not found in the MENU above, say it's not available.
- Recommend coffee drinks, food, and desserts based on the actual menu.
- Maximum of 6 sentences unless listing the full menu.
- Friendly and professional. Reply in Taglish, matching the customer's language.

Customer:
{message}
"""

    max_retries = 3

    for attempt in range(max_retries):

        try:

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            reply = getattr(response, "text", None)

            if not reply:
                reply = "Sorry, I couldn't generate a response."

            history.append({"user": message, "bot": reply})
            session["chat_history"] = history[-10:]
            session.modified = True

            return jsonify({
                "reply": reply
            })

        except Exception as e:

            error = str(e)

            if ("503" in error or "UNAVAILABLE" in error) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue

            if "503" in error or "UNAVAILABLE" in error:
                reply = (
                    "Medyo maraming gumagamit ng CoffeeBot ngayon. "
                    "Pakisubukan na lang ulit sa loob ng ilang segundo. 🙏"
                )
            elif "429" in error or "RESOURCE_EXHAUSTED" in error:
                reply = (
                    "CoffeeBot is temporarily unavailable because the Gemini API "
                    "quota has been exceeded. Please try again later."
                )
            else:
                reply = f"AI Error: {error}"

            return jsonify({
                "reply": reply
            })


@app.route("/admin")
@admin_required
def admin_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM products")
    total_products = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM orders")
    total_orders = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM orders WHERE status='Pending'")
    pending_orders = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(total), 0) AS sales FROM orders WHERE status='Completed'")
    total_sales = cursor.fetchone()["sales"]

    cursor.execute("""
        SELECT product_name, SUM(quantity) AS total_qty
        FROM orders
        GROUP BY product_name
        ORDER BY total_qty DESC
        LIMIT 5
    """)
    best_sellers = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_products=total_products,
        total_orders=total_orders,
        pending_orders=pending_orders,
        total_sales=total_sales,
        best_sellers=best_sellers
    )


@app.route("/admin/products")
@admin_required
def admin_products():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products ORDER BY id DESC")
    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("admin/products.html", products=products)


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():

    if request.method == "POST":

        product_name = request.form["product_name"]
        category = request.form.get("category", "")
        description = request.form.get("description", "")
        price_raw = request.form["price"]

        # (added) new product detail fields
        stock_raw = request.form.get("stock", "0")
        ingredients = request.form.get("ingredients", "")
        calories_raw = request.form.get("calories", "").strip()
        caffeine = request.form.get("caffeine", "")
        sweetness = request.form.get("sweetness", "")
        bestseller = 1 if request.form.get("bestseller") == "on" else 0

        try:
            price = float(price_raw)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Invalid price. Please enter a valid positive number.")
            return redirect(url_for("admin_add_product"))

        # (added) validate stock
        try:
            stock = int(stock_raw) if stock_raw != "" else 0
            if stock < 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Invalid stock. Please enter a valid whole number.")
            return redirect(url_for("admin_add_product"))

        # (added) validate calories (optional field)
        calories = None
        if calories_raw != "":
            try:
                calories = int(calories_raw)
                if calories < 0:
                    raise ValueError
            except (TypeError, ValueError):
                flash("Invalid calories. Please enter a valid whole number.")
                return redirect(url_for("admin_add_product"))

        image_path = ""

        if "image" in request.files and request.files["image"].filename != "":

            file = request.files["image"]

            if not allowed_file(file.filename):
                flash("Invalid image type. Please upload a PNG, JPG, JPEG, GIF, or WEBP image.")
                return redirect(url_for("admin_add_product"))

            filename = make_unique_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            image_path = f"uploads/{filename}"

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO products
            (product_name, category, description, price, image, stock, ingredients, calories, caffeine, sweetness, bestseller)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            product_name,
            category,
            description,
            price,
            image_path,
            stock,
            ingredients,
            calories,
            caffeine,
            sweetness,
            bestseller
        ))

        conn.commit()

        cursor.close()
        conn.close()

        flash("Product added!")

        return redirect(url_for("admin_products"))

    return render_template("admin/product_form.html", product=None)


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products WHERE id=%s", (product_id,))
    product = cursor.fetchone()

    if not product:
        cursor.close()
        conn.close()
        flash("Product not found.")
        return redirect(url_for("admin_products"))

    if request.method == "POST":

        product_name = request.form["product_name"]
        category = request.form.get("category", "")
        description = request.form.get("description", "")
        price_raw = request.form["price"]

        # (added) new product detail fields
        stock_raw = request.form.get("stock", "0")
        ingredients = request.form.get("ingredients", "")
        calories_raw = request.form.get("calories", "").strip()
        caffeine = request.form.get("caffeine", "")
        sweetness = request.form.get("sweetness", "")
        bestseller = 1 if request.form.get("bestseller") == "on" else 0

        try:
            price = float(price_raw)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            cursor.close()
            conn.close()
            flash("Invalid price. Please enter a valid positive number.")
            return redirect(url_for("admin_edit_product", product_id=product_id))

        # (added) validate stock
        try:
            stock = int(stock_raw) if stock_raw != "" else 0
            if stock < 0:
                raise ValueError
        except (TypeError, ValueError):
            cursor.close()
            conn.close()
            flash("Invalid stock. Please enter a valid whole number.")
            return redirect(url_for("admin_edit_product", product_id=product_id))

        # (added) validate calories (optional field)
        calories = None
        if calories_raw != "":
            try:
                calories = int(calories_raw)
                if calories < 0:
                    raise ValueError
            except (TypeError, ValueError):
                cursor.close()
                conn.close()
                flash("Invalid calories. Please enter a valid whole number.")
                return redirect(url_for("admin_edit_product", product_id=product_id))

        image_path = product["image"]

        if "image" in request.files and request.files["image"].filename != "":

            file = request.files["image"]

            if not allowed_file(file.filename):
                cursor.close()
                conn.close()
                flash("Invalid image type. Please upload a PNG, JPG, JPEG, GIF, or WEBP image.")
                return redirect(url_for("admin_edit_product", product_id=product_id))

            filename = make_unique_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            image_path = f"uploads/{filename}"

        update_cursor = conn.cursor()

        update_cursor.execute("""
            UPDATE products
            SET product_name=%s, category=%s, description=%s, price=%s, image=%s,
                stock=%s, ingredients=%s, calories=%s, caffeine=%s, sweetness=%s, bestseller=%s
            WHERE id=%s
        """, (
            product_name,
            category,
            description,
            price,
            image_path,
            stock,
            ingredients,
            calories,
            caffeine,
            sweetness,
            bestseller,
            product_id
        ))

        conn.commit()

        update_cursor.close()
        cursor.close()
        conn.close()

        flash("Product updated!")

        return redirect(url_for("admin_products"))

    cursor.close()
    conn.close()

    return render_template("admin/product_form.html", product=product)


@app.route("/admin/products/delete/<int:product_id>")
@admin_required
def admin_delete_product(product_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM products WHERE id=%s", (product_id,))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Product deleted.")

    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("admin/orders.html", orders=orders)


@app.route("/admin/orders/update_status/<int:order_id>/<status>")
@admin_required
def admin_update_order_status(order_id, status):

    valid_statuses = ["Pending", "Preparing", "Completed", "Cancelled"]

    if status not in valid_statuses:
        flash("Invalid status.")
        return redirect(url_for("admin_orders"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    target_order = cursor.fetchone()

    if not target_order:
        cursor.close()
        conn.close()
        flash("Order not found.")
        return redirect(url_for("admin_orders"))

    update_cursor = conn.cursor()
    update_cursor.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))

    conn.commit()

    update_cursor.close()
    cursor.close()
    conn.close()

    status_messages = {
        "Preparing": f"Your order for {target_order['product_name']} is now being prepared.",
        "Completed": f"Your order for {target_order['product_name']} is ready/completed. Enjoy!",
        "Cancelled": f"Your order for {target_order['product_name']} was cancelled by the shop."
    }

    if status in status_messages:
        create_notification(
            target_order["user_id"],
            status_messages[status],
            link=url_for("orders")
        )

    flash(f"Order #{order_id} marked as {status}.")

    return redirect(url_for("admin_orders"))


@app.route("/admin/users")
@admin_required
def admin_users():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, fullname, username, profile_image, is_admin
        FROM users
        ORDER BY id DESC
    """)
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("admin/users.html", users=users)


@app.errorhandler(404)
def not_found(error):

    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(error):

    return render_template("500.html"), 500


if __name__ == "__main__":

    print("=" * 60)
    print("☕ Tara Kape Coffee Shop")
    print("CoffeeBot AI Ready")
    print("Server Running...")
    print("http://127.0.0.1:5000")
    print("=" * 60)

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )