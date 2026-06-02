"""
admin_routes.py  —  ChocoBite Admin Portal
==========================================
Place at: E:\\chocobite\\admin_routes.py

Templates needed (E:\\chocobite\\templates\\admin\\):
    base.html
    dashboard.html

Login via the regular store login modal — no separate admin login page.
"""

from flask import (Blueprint, render_template, request, jsonify,
                   session, redirect, current_app)
from werkzeug.security import generate_password_hash
from functools import wraps
import datetime, uuid

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

SESSION_TIMEOUT = 30  # minutes


# ── Lazy DB access — uses app.py's existing Atlas connection ──────────────────
def get_db():
    """Return the db object from app.py's MongoClient (same Atlas connection)."""
    from app import db
    return db


# ── Auth guard ────────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect("/")

        last = session.get("admin_last_active")
        if last and isinstance(last, str):
            try:
                last_dt = datetime.datetime.fromisoformat(last)
                elapsed = (datetime.datetime.utcnow() - last_dt).total_seconds() / 60
                if elapsed > SESSION_TIMEOUT:
                    session.clear()
                    return redirect("/?admin_timeout=1")
            except Exception:
                pass

        session["admin_last_active"] = datetime.datetime.utcnow().isoformat()
        return f(*args, **kwargs)
    return decorated


# ── Logout ────────────────────────────────────────────────────────────────────
@admin_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── Session keep-alive ────────────────────────────────────────────────────────
@admin_bp.route("/api/session-check")
def session_check():
    if not session.get("admin_id"):
        return jsonify(active=False)
    session["admin_last_active"] = datetime.datetime.utcnow().isoformat()
    return jsonify(active=True)


# ── Admin profile (email + last login) ───────────────────────────────────
@admin_bp.route("/api/profile")
def admin_profile():
    if not session.get("admin_id"):
        return jsonify(success=False)
    db    = get_db()
    admin = db["admins"].find_one({"admin_id": session["admin_id"]}, {"_id": 0, "password_hash": 0})
    if not admin:
        return jsonify(success=False)
    last = admin.get("last_login")
    last_str = last.strftime("%d %b %Y, %I:%M %p UTC") if last and hasattr(last, "strftime") else "First login"
    return jsonify(
        success    = True,
        name       = admin.get("username", "Admin"),
        email      = admin.get("email", ""),
        role       = admin.get("role", "admin"),
        last_login = last_str,
    )


# ── Dashboard page ────────────────────────────────────────────────────────────
@admin_bp.route("/")
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    return render_template(
        "admin/dashboard.html",
        admin_name  = session.get("admin_name", "Admin"),
        admin_role  = session.get("admin_role", "admin"),
        active_page = "dashboard",
    )


# ── Stats API ─────────────────────────────────────────────────────────────────
@admin_bp.route("/api/stats")
@admin_required
def stats():
    db    = get_db()
    now   = datetime.datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_orders  = list(db["orders"].find({"booked_at": {"$gte": today}}))
    revenue_today = sum(
        float(o.get("total_amount", 0)) for o in today_orders
        if o.get("order_status") != "cancelled"
        and o.get("payment_status") == "Paid"   # only count confirmed payments
    )

    processing = db["orders"].count_documents({"order_status": "processing"})
    delivered  = db["orders"].count_documents({"order_status": "delivered"})
    cancelled  = db["orders"].count_documents({"order_status": "cancelled"})

    low_stock = list(db["products"].find(
        {"stock_quantity": {"$lt": 7}},
        {"name": 1, "stock_quantity": 1, "product_id": 1,
         "category_id": 1, "_id": 0}
    ).sort("stock_quantity", 1))  # lowest stock first

    # Revenue chart: use payment date — cod_paid_at for COD, booked_at for online
    revenue_7d = []
    for i in range(6, -1, -1):
        ds  = today - datetime.timedelta(days=i)
        de  = ds + datetime.timedelta(days=1)
        # Online payments: paid when order was placed
        online_rev = sum(
            float(o.get("total_amount", 0))
            for o in db["orders"].find(
                {"booked_at": {"$gte": ds, "$lt": de},
                 "payment_method": "online",
                 "order_status":   {"$ne": "cancelled"},
                 "payment_status": "Paid"},
                {"total_amount": 1}
            )
        )
        # COD payments: paid when admin marks as paid (cod_paid_at)
        cod_rev = sum(
            float(o.get("total_amount", 0))
            for o in db["orders"].find(
                {"cod_paid_at": {"$gte": ds, "$lt": de},
                 "payment_method": "cod",
                 "payment_status": "Paid"},
                {"total_amount": 1}
            )
        )
        revenue_7d.append({
            "date":    ds.strftime("%d %b"),
            "revenue": round(online_rev + cod_rev)
        })

    recent = list(db["orders"].find(
        {},
        {"_id": 0, "order_id": 1, "user_name": 1, "total_amount": 1,
         "order_status": 1, "payment_method": 1, "booked_at": 1,
         "is_custom_gift": 1, "is_custom_design": 1}
    ).sort("booked_at", -1).limit(8))

    for o in recent:
        bk = o.get("booked_at")
        if bk and hasattr(bk, "strftime"):
            o["booked_at"] = bk.strftime("%d %b %Y, %I:%M %p")

    from collections import Counter
    pc = Counter()
    for o in db["orders"].find({"order_status": {"$ne": "cancelled"}}, {"items": 1}):
        for item in o.get("items", []):
            pid = item.get("product_id", "")
            if pid and not pid.startswith("SEASONAL-"):
                pc[pid] += int(item.get("quantity", 1))

    top_products = []
    for pid, count in pc.most_common(5):
        p = db["products"].find_one({"product_id": pid}, {"name": 1, "_id": 0})
        if p:
            top_products.append({"name": p["name"], "count": count})

    # Pincode region counts (users)
    udupi_customers = db["users"].count_documents({"pincode_region": "udupi"})
    other_customers = db["users"].count_documents({"pincode_region": "other"})

    # Aggregate all pincodes set on products and classify
    all_product_pins = []
    for prod in db["products"].find({"delivery_pincodes": {"$exists": True, "$ne": []}},
                                     {"delivery_pincodes": 1, "_id": 0}):
        all_product_pins.extend(prod.get("delivery_pincodes") or [])
    unique_pins = list(set(all_product_pins))
    udupi_pins  = [p for p in unique_pins if p[:3] in ('576', '574')]
    other_pins  = [p for p in unique_pins if p[:3] not in ('576', '574')]

    return jsonify(
        revenue_today  = round(revenue_today),
        orders_today   = len(today_orders),
        total_orders   = db["orders"].count_documents({}),
        total_users    = db["users"].count_documents({}),
        total_products = db["products"].count_documents({}),
        processing=processing, delivered=delivered, cancelled=cancelled,
        low_stock=low_stock, revenue_7d=revenue_7d,
        recent_orders=recent, top_products=top_products,
        udupi_customers=udupi_customers,
        other_customers=other_customers,
        udupi_product_pins=len(udupi_pins),
        other_product_pins=len(other_pins),
    )


# ── Seed admin — visit ONCE at /admin/seed-admin ─────────────────────────────
@admin_bp.route("/seed-admin")
def seed_admin():
    db = get_db()
    if db["admins"].count_documents({}) > 0:
        return "<h2 style='font-family:sans-serif'>Admin already exists.</h2>", 403

    db["admins"].insert_one({
        "admin_id":      str(uuid.uuid4()),
        "username":      "ChocoBite Admin",
        "email":         "chocobite999x@gmail.com",
        "password_hash": generate_password_hash("ufxaaliyzfkavugo"),
        "role":          "superadmin",
        "created_at":    datetime.datetime.utcnow(),
        "last_login":    None,
    })
    return """
    <div style='font-family:sans-serif;max-width:440px;margin:60px auto;padding:24px;
                border:1px solid #d4820a;border-radius:12px;background:#111;color:#e8d5b0'>
        <h2 style='color:#f5c842'>&#10003; Admin Created in Atlas!</h2>
        <p><b>Email:</b> chocobite999x@gmail.com</p>
        <p><b>Password:</b> ufxaaliyzfkavugo</p>
        <p style='margin-top:12px;color:#a07840'>
            Use the regular Login button on the store homepage with these credentials.
            You will be automatically redirected to the admin portal.
        </p>
        <p style='color:#e04040;margin-top:10px;font-size:13px'>
            &#9888; Change password after first login. Remove this route in production.
        </p>
    </div>"""


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS — Change Password
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/settings")
@admin_required
def settings():
    return render_template("admin/settings.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="settings")


@admin_bp.route("/api/change-password", methods=["POST"])
@admin_required
def change_password():
    from werkzeug.security import check_password_hash, generate_password_hash
    db   = get_db()
    data = request.get_json()
    current  = data.get("current_password", "")
    new_pw   = data.get("new_password", "")
    confirm  = data.get("confirm_password", "")

    admin = db["admins"].find_one({"admin_id": session["admin_id"]})
    if not admin:
        return jsonify(success=False, message="Admin not found")
    if not check_password_hash(admin["password_hash"], current):
        return jsonify(success=False, message="Current password is incorrect")
    if len(new_pw) < 8:
        return jsonify(success=False, message="Password must be at least 8 characters")
    if new_pw != confirm:
        return jsonify(success=False, message="Passwords do not match")

    db["admins"].update_one(
        {"admin_id": session["admin_id"]},
        {"$set": {"password_hash": generate_password_hash(new_pw),
                  "password_changed_at": datetime.datetime.utcnow()}}
    )

    # Send confirmation email
    try:
        from app import send_email, email_wrap, EMAIL_USER
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>Hello <strong style='color:#f5c842'>"
            f"{admin.get('username','Admin')}</strong>,</p>"
            f"<p style='color:#e8d5b0;font-size:15px;margin-top:12px'>"
            f"Your admin password was successfully changed.</p>"
            f"<p style='color:#a07840;font-size:13px;margin-top:10px'>"
            f"Time: {datetime.datetime.utcnow().strftime('%d %b %Y, %I:%M %p UTC')}<br>"
            f"If you did not make this change, contact support immediately.</p>"
        )
        send_email(admin.get("email", EMAIL_USER),
                   "ChocoBite Admin — Password Changed 🔐",
                   email_wrap("Password Changed", body))
    except Exception:
        pass

    return jsonify(success=True, message="Password updated successfully!")


# ══════════════════════════════════════════════════════════════════════════════
# ORDERS — Full Management
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/orders")
@admin_required
def orders():
    return render_template("admin/orders.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="orders")


@admin_bp.route("/api/orders")
@admin_required
def get_orders():
    db         = get_db()
    status     = request.args.get("status", "")
    payment    = request.args.get("payment", "")
    order_type = request.args.get("type", "")      # custom / gift / design
    search     = request.args.get("search", "").strip()
    page       = int(request.args.get("page", 1))
    per_page   = 20

    query = {}
    if status:
        query["order_status"] = status
    if payment == "cod":
        query["payment_method"] = "cod"
    elif payment == "online":
        query["payment_method"] = "online"
    if order_type == "gift":
        query["is_custom_gift"] = True
    elif order_type == "design":
        query["is_custom_design"] = True
    elif order_type == "custom":
        query["$or"] = [{"is_custom_gift": True}, {"is_custom_design": True}]
    if search:
        query["$or"] = [
            {"order_id":   {"$regex": search, "$options": "i"}},
            {"user_name":  {"$regex": search, "$options": "i"}},
            {"user_email": {"$regex": search, "$options": "i"}},
        ]

    total   = db["orders"].count_documents(query)
    skip    = (page - 1) * per_page
    orders  = list(db["orders"].find(query, {"_id": 0})
                               .sort("booked_at", -1)
                               .skip(skip).limit(per_page))

    for o in orders:
        for k in ("booked_at", "estimated_arrival"):
            v = o.get(k)
            if v and hasattr(v, "strftime"):
                o[k] = v.strftime("%d %b %Y, %I:%M %p")

    return jsonify(orders=orders, total=total, page=page, per_page=per_page)


# ── Ship order ────────────────────────────────────────────────────────────────
@admin_bp.route("/api/order/ship", methods=["POST"])
@admin_required
def ship_order():
    db       = get_db()
    order_id = request.get_json().get("order_id", "")
    order    = db["orders"].find_one({"order_id": order_id})
    if not order:
        return jsonify(success=False, message="Order not found")
    if order.get("order_status") in ("delivered", "cancelled"):
        return jsonify(success=False, message="Cannot ship this order")

    db["orders"].update_one(
        {"order_id": order_id},
        {"$set": {"order_status": "dispatched",
                  "dispatched_at": datetime.datetime.utcnow()}}
    )

    # Email customer
    try:
        from app import send_email, email_wrap
        eta = order.get("estimated_arrival")
        eta_str = eta.strftime("%d %b %Y") if eta and hasattr(eta,"strftime") else "soon"
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>Hi <strong style='color:#f5c842'>"
            f"{order.get('user_name','there')}</strong>,</p>"
            f"<p style='color:#e8d5b0;font-size:15px;margin-top:12px'>"
            f"Great news! Your ChocoBite order has been <strong style='color:#64b5f6'>dispatched</strong> "
            f"and is on its way to you. 🚚</p>"
            f"<p style='color:#e8d5b0;font-size:14px;margin-top:10px'>"
            f"<strong style='color:#d4820a'>Order ID:</strong> "
            f"<code style='color:#f5c842'>{order_id}</code><br>"
            f"<strong style='color:#d4820a'>Estimated Arrival:</strong> {eta_str}</p>"
            f"<p style='color:#a07840;font-size:13px;margin-top:14px'>"
            f"Sit back and get ready for some chocolate magic! 🍫</p>"
        )
        send_email(order.get("user_email",""), "ChocoBite — Your Order is On Its Way! 🚚",
                   email_wrap("Order Dispatched", body))
    except Exception:
        pass

    return jsonify(success=True, message="Order marked as dispatched. Customer notified.")


# ── Mark COD payment received ─────────────────────────────────────────────────
@admin_bp.route("/api/order/mark-paid", methods=["POST"])
@admin_required
def mark_paid():
    db       = get_db()
    order_id = request.get_json().get("order_id", "")
    order    = db["orders"].find_one({"order_id": order_id})
    if not order:
        return jsonify(success=False, message="Order not found")
    if order.get("payment_status") == "Paid":
        return jsonify(success=False, message="Already marked as paid")

    amount = float(order.get("total_amount", 0))

    db["orders"].update_one(
        {"order_id": order_id},
        {"$set": {"payment_status": "Paid",
                  "cod_paid_at": datetime.datetime.utcnow()}}
    )

    # Record in payments collection
    db["payments"].insert_one({
        "payment_id": str(uuid.uuid4()),
        "order_id":   order_id,
        "user_id":    order.get("user_id"),
        "user_name":  order.get("user_name"),
        "user_email": order.get("user_email"),
        "amount":     amount,
        "method":     "COD",
        "status":     "success",
        "marked_by":  session.get("admin_name"),
        "created_at": datetime.datetime.utcnow(),
    })

    # Email customer
    try:
        from app import send_email, email_wrap
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>Hi <strong style='color:#f5c842'>"
            f"{order.get('user_name','there')}</strong>,</p>"
            f"<p style='color:#e8d5b0;font-size:15px;margin-top:12px'>"
            f"Your payment of <strong style='color:#f5c842'>₹{int(amount)}</strong> "
            f"for order <code style='color:#f5c842'>{order_id[:8]}…</code> "
            f"has been received and confirmed. ✅</p>"
            f"<p style='color:#6fcf97;font-size:14px;margin-top:10px'>"
            f"Payment Status: <strong>Paid</strong></p>"
            f"<p style='color:#a07840;font-size:13px;margin-top:14px'>Thank you for your purchase! 🍫</p>"
        )
        send_email(order.get("user_email",""), "ChocoBite — Payment Received ✅",
                   email_wrap("Payment Confirmed", body))
    except Exception:
        pass

    return jsonify(success=True, message="Payment marked as received. Customer notified.",
                   amount=amount)


# ── Mark order delivered ──────────────────────────────────────────────────────
@admin_bp.route("/api/order/deliver", methods=["POST"])
@admin_required
def deliver_order():
    db       = get_db()
    order_id = request.get_json().get("order_id", "")
    order    = db["orders"].find_one({"order_id": order_id})
    if not order:
        return jsonify(success=False, message="Order not found")

    db["orders"].update_one(
        {"order_id": order_id},
        {"$set": {"order_status": "delivered",
                  "delivered_at": datetime.datetime.utcnow()}}
    )

    try:
        from app import send_email, email_wrap
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>Hi <strong style='color:#f5c842'>"
            f"{order.get('user_name','there')}</strong>,</p>"
            f"<p style='color:#e8d5b0;font-size:15px;margin-top:12px'>"
            f"Your ChocoBite order has been <strong style='color:#6fcf97'>delivered</strong>! "
            f"We hope you love every bite. 🍫</p>"
            f"<p style='color:#a07840;font-size:13px;margin-top:14px'>"
            f"Order ID: <code style='color:#f5c842'>{order_id}</code></p>"
        )
        send_email(order.get("user_email",""), "ChocoBite — Order Delivered! 🍫",
                   email_wrap("Order Delivered", body))
    except Exception:
        pass

    return jsonify(success=True, message="Order marked as delivered.")

# ── Total revenue (all time, paid only) ──────────────────────────────────────
@admin_bp.route("/api/revenue")
@admin_required
def total_revenue():
    db = get_db()
    # Total paid: online orders + COD orders that admin confirmed
    pipeline = [
        {"$match": {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}}},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
    ]
    result = list(db["orders"].aggregate(pipeline))
    total  = round(result[0]["total"]) if result else 0
    return jsonify(total_revenue=total)


# ── Timer check — overdue orders (ship_by passed, not yet dispatched) ─────────
@admin_bp.route("/api/orders/overdue")
@admin_required
def overdue_orders():
    db  = get_db()
    now = datetime.datetime.utcnow()
    overdue = list(db["orders"].find(
        {"order_status": "processing",
         "ship_by": {"$lt": now}},
        {"_id": 0, "order_id": 1, "user_name": 1, "ship_by": 1,
         "estimated_arrival": 1, "total_amount": 1}
    ))
    for o in overdue:
        for k in ("ship_by", "estimated_arrival"):
            v = o.get(k)
            if v and hasattr(v, "isoformat"):
                o[k] = v.isoformat()
    return jsonify(overdue=overdue, count=len(overdue))


# ── Send overdue email to admin (called by JS timer) ─────────────────────────
@admin_bp.route("/api/orders/overdue-notify", methods=["POST"])
@admin_required
def overdue_notify():
    db   = get_db()
    data = request.get_json()
    oid  = data.get("order_id", "")
    order = db["orders"].find_one({"order_id": oid})
    if not order:
        return jsonify(success=False)
    try:
        from app import send_email, email_wrap, EMAIL_USER
        eta = order.get("estimated_arrival")
        eta_str = eta.strftime("%d %b %Y") if eta and hasattr(eta,"strftime") else "soon"
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>&#9888; <strong style='color:#e04040'>URGENT:</strong> "
            f"Order <code style='color:#f5c842'>{oid[:8]}</code> is overdue for shipping!</p>"
            f"<p style='color:#e8d5b0;font-size:14px;margin-top:10px'>"
            f"Customer: <strong>{order.get('user_name','—')}</strong><br>"
            f"Expected delivery: <strong style='color:#e04040'>{eta_str}</strong><br>"
            f"Amount: &#8377;{order.get('total_amount','—')}</p>"
            f"<p style='color:#e04040;font-size:14px;margin-top:12px'>"
            f"<strong>Please ship this order immediately!</strong></p>"
        )
        send_email(EMAIL_USER, f"🚨 URGENT: Ship Order #{oid[:8]} NOW — Overdue!",
                   email_wrap("Overdue Shipping Alert", body))
    except Exception as e:
        print(f"[OVERDUE NOTIFY] {e}")
    return jsonify(success=True)

# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/products")
@admin_required
def products():
    return render_template("admin/products.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="products")


@admin_bp.route("/inventory")
@admin_required
def inventory():
    return render_template("admin/inventory.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="inventory")


@admin_bp.route("/api/products")
@admin_required
def admin_get_products():
    """Return all products for admin — including inactive ones."""
    db     = get_db()
    search = request.args.get("search", "").strip()
    cat    = request.args.get("category", "")
    status = request.args.get("status", "")   # active / inactive / all

    query = {}
    if search:
        query["$or"] = [
            {"name":        {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]
    if cat:
        query["category_id"] = int(cat)
    if status == "active":
        query["is_active"] = {"$ne": False}
    elif status == "inactive":
        query["is_active"] = False

    products = list(db["products"].find(query, {"_id": 0})
                                  .sort("category_id", 1))
    return jsonify(products=products)


import re as _re

def _parse_pincodes(raw):
    """
    Parse comma-separated pincode tokens.
    Accepts:
      - Full 6-digit codes:   576201, 574199
      - Prefix patterns:      576xxx, 574xxx  (stored as '576xxx')
    Validation uses only the first 3 digits.
    """
    if not raw:
        return []
    result = []
    for p in str(raw).split(','):
        p = p.strip()
        if len(p) != 6:
            continue
        # Accept: all digits  OR  3 digits + xxx/XXX
        if _re.match(r'^[0-9]{6}$', p):
            result.append(p)
        elif _re.match(r'^[0-9]{3}[xX]{3}$', p):
            result.append(p[:3] + 'xxx')   # normalise to lowercase xxx
    return result


def _classify_pincodes(pincodes):
    """Split pincodes into udupi and other lists (checks first 3 digits only)."""
    udupi = [p for p in pincodes if p[:3] in ('576', '574')]
    other = [p for p in pincodes if p[:3] not in ('576', '574')]
    return udupi, other


# Image upload route (ADDED: /admin/api/upload-image)
# Saves uploaded product image to static/images/ and returns its URL
@admin_bp.route("/api/upload-image", methods=["POST"])
@admin_required
def upload_product_image():
    import os, uuid as _uuid
    from werkzeug.utils import secure_filename
    from flask import current_app

    if "file" not in request.files:
        return jsonify(success=False, message="No file part")
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify(success=False, message="No file selected")

    ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in ALLOWED:
        return jsonify(success=False, message="Only jpg/jpeg/png/webp/gif allowed")

    # CHANGE: saves to <app_root>/static/images/<uuid><ext>
    filename    = str(_uuid.uuid4()) + ext
    save_folder = os.path.join(current_app.root_path, "static", "images")
    os.makedirs(save_folder, exist_ok=True)
    f.save(os.path.join(save_folder, filename))

    url = "/static/images/" + filename
    return jsonify(success=True, url=url)


@admin_bp.route("/api/product/add", methods=["POST"])
@admin_required
def add_product():
    """
    Add a new product to the database.

    About images:
    ─────────────
    Images on your laptop cannot be directly used via a URL because Flask serves
    files from its own static folder. To use a local image:
      1. Copy the image into: E:/chocobite/static/images/
      2. Then in the image URL field enter:  /static/images/your_filename.jpg
    Flask will then serve it correctly.

    Alternatively, upload the image to a free host like:
      - Cloudinary (free tier): https://cloudinary.com
      - ImgBB: https://imgbb.com
    Then paste the URL into the image field.
    """
    db   = get_db()
    data = request.get_json()

    # Validate required fields
    if not data.get("name","").strip():
        return jsonify(success=False, message="Product name is required")
    if not data.get("price"):
        return jsonify(success=False, message="Price is required")
    if not data.get("category_id"):
        return jsonify(success=False, message="Category is required")

    product = {
        "product_id":     str(uuid.uuid4()),
        "name":           data.get("name","").strip(),
        "description":    data.get("description","").strip(),
        "tagline":        data.get("tagline","").strip(),
        "price":          float(data.get("price", 0)),
        "mrp":            float(data.get("mrp") or data.get("price", 0)),
        "weight":         data.get("weight","").strip(),
        "category_id":    int(data.get("category_id", 1)),
        "pack_type":      data.get("pack_type","").strip(),
        "is_sugarless":   bool(data.get("is_sugarless", False)),
        "image_url":      data.get("image_url","").strip(),
        "stock_quantity": int(data.get("stock_quantity", 0)),
        "rating":         float(data.get("rating", 4.5)),
        "why_this":       data.get("why_this","").strip(),
        "health_benefits":data.get("health_benefits","").strip(),
        "price_per_100g": data.get("price_per_100g","").strip(),
        "is_active":      True,   # active by default
        "created_at":     datetime.datetime.utcnow(),
        "delivery_pincodes": _parse_pincodes(data.get("delivery_pincodes", "")),
    }
    # ── Launch offer: 50% off for first 10 buyers, valid 3 days ──────────────
    offer_price     = round(product["price"] * 0.5, 2)
    offer_expires   = datetime.datetime.utcnow() + datetime.timedelta(days=3)
    product.update({
        "launch_offer": {
            "active":        True,
            "discount_pct":  50,
            "offer_price":   offer_price,        # actual discounted price
            "max_buyers":    10,                  # only first 10 customers
            "buyers_count":  0,                   # incremented on each purchase
            "expires_at":    offer_expires,
        }
    })

    db["products"].insert_one(product)
    product.pop("_id", None)

    # ── Notify ALL registered users about the new product ─────────────────────
    try:
        from app import send_email, email_wrap, EMAIL_USER
        users = list(db["users"].find({}, {"email": 1, "full_name": 1, "_id": 0}))
        cat_names = {1: "Cocoa Beans & Chips", 2: "Choco Powder", 3: "Flavoured Chocolates"}
        cat_name  = cat_names.get(product["category_id"], "Chocolate")
        img_block = (
            f"<img src='{product['image_url']}' alt='{product['name']}' "
            f"style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;"
            f"margin-bottom:18px;border:2px solid #d4820a'>"
        ) if product.get("image_url") else ""

        for user in users:
            body = (
                f"<p style='color:#e8d5b0;font-size:15px'>Hi <strong style='color:#f5c842'>"
                f"{user.get('full_name','there')}</strong>,</p>"
                f"<p style='color:#e8d5b0;font-size:15px;margin:12px 0'>"
                f"We just added something new to ChocoBite! &#127851;</p>"
                f"{img_block}"
                f"<div style='background:#111;border:1px solid #d4820a;border-radius:12px;"
                f"padding:20px;margin:16px 0'>"
                f"<p style='color:#f5c842;font-size:18px;font-weight:bold;margin:0 0 6px'>"
                f"{product['name']}</p>"
                f"<p style='color:#a07840;font-size:13px;margin:0 0 12px'>{cat_name}</p>"
                f"<p style='color:#e8d5b0;font-size:14px;margin:0 0 16px'>"
                f"{product.get('tagline') or product.get('description','')[:80]}</p>"
                f"<div style='background:linear-gradient(135deg,#8b0000,#d4820a);"
                f"border-radius:10px;padding:16px;text-align:center;margin-bottom:14px'>"
                f"<p style='color:#fff;font-size:13px;margin:0 0 6px;letter-spacing:2px;text-transform:uppercase'>"
                f"&#127381; Launch Offer — First 10 Buyers Only!</p>"
                f"<p style='color:#f5c842;font-size:28px;font-weight:bold;margin:0'>"
                f"50% OFF</p>"
                f"<p style='color:#fff;font-size:14px;margin:4px 0 0'>"
                f"<s style='color:#aaa'>&#8377;{product['price']}</s>"
                f"&nbsp;&rarr;&nbsp;"
                f"<strong>&#8377;{offer_price}</strong></p>"
                f"<p style='color:#ffd700;font-size:11px;margin:8px 0 0'>"
                f"&#9201; Offer expires in 3 days &bull; Only 10 spots available</p>"
                f"</div>"
                f"<a href='http://localhost:5000/product/{product['product_id']}' "
                f"style='display:block;background:linear-gradient(135deg,#d4820a,#b5690a);"
                f"color:#000;text-align:center;padding:13px;border-radius:8px;"
                f"font-weight:bold;font-size:15px;text-decoration:none'>"
                f"Grab This Deal &#8594;</a>"
                f"</div>"
                f"<p style='color:#7a6040;font-size:12px;margin-top:14px'>"
                f"Hurry! Only the first 10 customers get this price. After that it's &#8377;{product['price']}.</p>"
            )
            send_email(
                user["email"],
                f"&#127381; New: {product['name']} — 50% OFF for First 10 Buyers!",
                email_wrap(f"New Product: {product['name']}", body)
            )
    except Exception as e:
        print(f"[LAUNCH EMAIL] {e}")

    return jsonify(success=True,
                   message=f"Product added! Launch offer created. {len(users) if 'users' in dir() else 0} users notified.",
                   product=product)


@admin_bp.route("/api/product/edit", methods=["POST"])
@admin_required
def edit_product():
    """Update an existing product in the database."""
    db         = get_db()
    data       = request.get_json()
    product_id = data.get("product_id","")

    if not product_id:
        return jsonify(success=False, message="Product ID required")

    existing = db["products"].find_one({"product_id": product_id})
    if not existing:
        return jsonify(success=False, message="Product not found")

    updates = {}
    field_map = {
        "name":           str,
        "description":    str,
        "tagline":        str,
        "weight":         str,
        "pack_type":      str,
        "image_url":      str,
        "why_this":       str,
        "health_benefits":str,
        "price_per_100g": str,
    }
    for field, cast in field_map.items():
        if field in data:
            updates[field] = cast(data[field]).strip() if cast == str else cast(data[field])

    for field in ("price", "mrp"):
        if field in data and data[field] != "":
            updates[field] = float(data[field])

    if "category_id" in data:
        updates["category_id"] = int(data["category_id"])
    if "stock_quantity" in data:
        updates["stock_quantity"] = int(data["stock_quantity"])
    if "rating" in data:
        updates["rating"] = float(data["rating"])
    if "is_sugarless" in data:
        updates["is_sugarless"] = bool(data["is_sugarless"])

    if "delivery_pincodes" in data:
        raw_pins = data["delivery_pincodes"]
        if isinstance(raw_pins, list):
            updates["delivery_pincodes"] = [p for p in raw_pins if len(str(p)) == 6 and str(p).isdigit()]
        else:
            updates["delivery_pincodes"] = _parse_pincodes(raw_pins)

    updates["updated_at"] = datetime.datetime.utcnow()

    db["products"].update_one({"product_id": product_id}, {"$set": updates})
    return jsonify(success=True, message="Product updated successfully!")


@admin_bp.route("/api/product/delete", methods=["POST"])
@admin_required
def delete_product():
    """
    Soft delete — sets is_active: False.
    Product stays in DB and existing orders are not affected.
    Use toggle-visibility to re-activate.
    """
    db         = get_db()
    product_id = request.get_json().get("product_id","")
    if not product_id:
        return jsonify(success=False, message="Product ID required")

    db["products"].update_one(
        {"product_id": product_id},
        {"$set": {"is_active": False, "deleted_at": datetime.datetime.utcnow()}}
    )
    return jsonify(success=True, message="Product hidden from store (soft delete).")


@admin_bp.route("/api/product/toggle-visibility", methods=["POST"])
@admin_required
def toggle_visibility():
    """Toggle product active/inactive without deleting."""
    db         = get_db()
    data       = request.get_json()
    product_id = data.get("product_id","")
    active     = data.get("active", True)

    db["products"].update_one(
        {"product_id": product_id},
        {"$set": {"is_active": bool(active)}}
    )
    state = "visible in store" if active else "hidden from store"
    return jsonify(success=True, message=f"Product is now {state}.")


@admin_bp.route("/api/product/stock-update", methods=["POST"])
@admin_required
def stock_update():
    """Add or set stock quantity for a product."""
    db         = get_db()
    data       = request.get_json()
    product_id = data.get("product_id","")
    action     = data.get("action","add")  # 'add' or 'set'
    qty        = int(data.get("quantity", 0))

    product = db["products"].find_one({"product_id": product_id})
    if not product:
        return jsonify(success=False, message="Product not found")

    if action == "add":
        db["products"].update_one(
            {"product_id": product_id},
            {"$inc": {"stock_quantity": qty}}
        )
        new_qty = product.get("stock_quantity", 0) + qty
    else:
        db["products"].update_one(
            {"product_id": product_id},
            {"$set": {"stock_quantity": qty}}
        )
        new_qty = qty

    return jsonify(success=True,
                   message=f"Stock updated to {new_qty} units.",
                   new_quantity=new_qty)


@admin_bp.route("/api/categories")
@admin_required
def get_categories():
    """Return all categories for product form dropdowns."""
    db   = get_db()
    cats = list(db["categories"].find({}, {"_id": 0}))
    return jsonify(categories=cats)

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOMER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/customers")
@admin_required
def customers():
    return render_template("admin/customers.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="customers")


@admin_bp.route("/api/customers")
@admin_required
def get_customers():
    db     = get_db()
    search = request.args.get("search","").strip()
    page   = int(request.args.get("page", 1))
    per    = 20

    query = {}
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email":     {"$regex": search, "$options": "i"}},
            {"phone":     {"$regex": search, "$options": "i"}},
        ]

    total = db["users"].count_documents(query)
    users = list(db["users"].find(query,
        {"_id":0, "password_hash":0, "otp_code":0, "otp_expires":0}
    ).sort("created_at",-1).skip((page-1)*per).limit(per))

    # Enrich with order stats per user
    for u in users:
        uid    = u.get("user_id","")
        orders = list(db["orders"].find({"user_id": uid},
                      {"total_amount":1,"order_status":1,"payment_status":1}))
        u["total_orders"]  = len(orders)
        u["total_spent"]   = round(sum(
            float(o.get("total_amount",0)) for o in orders
            if o.get("payment_status") == "Paid"
        ))
        u["cancelled"]     = sum(1 for o in orders if o.get("order_status")=="cancelled")
        if isinstance(u.get("created_at"), datetime.datetime):
            u["created_at"] = u["created_at"].strftime("%d %b %Y")

    return jsonify(users=users, total=total, page=page, per_page=per)


@admin_bp.route("/api/customer/<user_id>/orders")
@admin_required
def customer_orders(user_id):
    db = get_db()
    orders = list(db["orders"].find({"user_id": user_id}, {"_id":0})
                              .sort("booked_at",-1).limit(20))
    for o in orders:
        for k in ("booked_at","estimated_arrival"):
            v = o.get(k)
            if v and hasattr(v,"strftime"):
                o[k] = v.strftime("%d %b %Y")
    return jsonify(orders=orders)


@admin_bp.route("/api/customer/delete", methods=["POST"])
@admin_required
def delete_customer():
    """
    GDPR-compliant delete: removes user account.
    Orders are anonymised (user_name → Deleted User, user_email → deleted).
    """
    db      = get_db()
    user_id = request.get_json().get("user_id","")
    user    = db["users"].find_one({"user_id": user_id})
    if not user:
        return jsonify(success=False, message="User not found")

    db["users"].delete_one({"user_id": user_id})
    db["orders"].update_many(
        {"user_id": user_id},
        {"$set": {"user_name": "Deleted User", "user_email": "deleted@account"}}
    )
    db["cart"].delete_many({"user_id": user_id})
    return jsonify(success=True, message="Customer account deleted (GDPR). Orders anonymised.")



# ══════════════════════════════════════════════════════════════════════════════
# SEASONAL OFFERS CONTROL (Priority 7)
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/seasonal")
@admin_required
def seasonal():
    return render_template("admin/seasonal.html",
                           admin_name=session.get("admin_name"),
                           admin_role=session.get("admin_role"),
                           active_page="seasonal")


@admin_bp.route("/api/seasonal/current")
@admin_required
def seasonal_current():
    """
    Return current season's ML offers + redemption counts + pinned overrides.
    How it works on the user side:
      - User opens Customize → Seasonal Offers tab
      - Frontend calls /api/seasonal-offers (in app.py)
      - That route checks the in-memory cache (_seasonal_cache)
      - If cache empty → runs sklearn KMeans on all orders vs products
      - Returns 7 offers — user sees them, clicks Redeem → buy wizard
      - On purchase, order saved with is_seasonal_offer:true → tracked here

    How the ML works:
      - Features per product: [purchases_this_season, total_purchases, rating, price]
      - StandardScaler normalises so price doesn't dominate
      - KMeans(k=3) clusters into: popular / medium / low-sellers
      - popular  → 14-17% discount (already sell well, small nudge)
      - medium   → 18-20% discount
      - low-sell → 21-24% discount (needs a boost)
      - Diversity: max 2-3 per category
      - Cache persists per season — clears on refresh or server restart
    """
    db = get_db()
    now = datetime.datetime.utcnow()
    m   = now.month
    season_name = ("Summer"  if 3<=m<=5  else
                   "Monsoon" if 6<=m<=9  else
                   "Autumn"  if 10<=m<=11 else "Winter")
    emojis = {"Summer":"☀️","Monsoon":"🌧️","Autumn":"🍂","Winter":"❄️"}
    emoji  = emojis.get(season_name,"🌿")

    # Get cached offers (same ones users see)
    try:
        import requests as _req
        # Call our own API internally to get what users see
        from flask import current_app
        with current_app.test_client() as c:
            with current_app.test_request_context():
                pass
    except Exception:
        pass

    # Directly use the cache from app.py
    try:
        import app as _app
        cached = _app._seasonal_cache.get(season_name)
        offers = cached["data"]["offers"] if cached else []
        generated_at = cached["generated_at"].strftime("%d %b %Y %H:%M UTC") if cached else None
    except Exception:
        offers = []
        generated_at = None

    # Get pinned overrides from DB
    pins = list(db["seasonal_pins"].find(
        {"season": season_name}, {"_id":0}
    ))
    pinned_ids    = {p["product_id"] for p in pins if p.get("action")=="pin"}
    removed_ids   = {p["product_id"] for p in pins if p.get("action")=="remove"}

    # Mark each offer with its pin/remove status
    for o in offers:
        pid = o.get("product_id","")
        o["is_pinned"]  = pid in pinned_ids
        o["is_removed"] = pid in removed_ids
        # Redemption count for this offer this season
        count = db["seasonal_redemptions"].count_documents({
            "product_id": pid, "season": season_name
        })
        o["redemptions"] = count

    # Pinned products not already in offers
    pinned_extra = []
    for p in pins:
        if p.get("action") == "pin" and p["product_id"] not in {o["product_id"] for o in offers}:
            prod = db["products"].find_one({"product_id": p["product_id"]}, {"_id":0})
            if prod:
                count = db["seasonal_redemptions"].count_documents({
                    "product_id": p["product_id"], "season": season_name
                })
                pinned_extra.append({
                    "product_id":  prod["product_id"],
                    "name":        prod["name"],
                    "image_url":   prod.get("image_url",""),
                    "price":       prod.get("price",0),
                    "final_price": round(prod.get("price",0)*0.82),
                    "discount":    18,
                    "is_pinned":   True,
                    "is_removed":  False,
                    "redemptions": count,
                    "pinned_by_admin": True,
                })

    # Total redemptions this season
    total_redemptions = db["seasonal_redemptions"].count_documents({"season": season_name})

    return jsonify(
        season       = season_name,
        emoji        = emoji,
        offers       = offers + pinned_extra,
        generated_at = generated_at,
        total_redemptions = total_redemptions,
        ml_available = True,
    )


@admin_bp.route("/api/seasonal/refresh", methods=["POST"])
@admin_required
def seasonal_refresh():
    """
    Force-refresh the ML cache. Next user request to /api/seasonal-offers
    will re-run KMeans on the latest order data from DB.
    Use this after: new orders come in, season changes, or you want fresh recommendations.
    """
    try:
        import app as _app
        _app._seasonal_cache.clear()
        msg = "ML cache cleared. Next user visit will re-run KMeans on latest order data."
    except Exception as e:
        msg = f"Cache cleared (app import issue: {e})"
    return jsonify(success=True, message=msg)


@admin_bp.route("/api/seasonal/pin", methods=["POST"])
@admin_required
def seasonal_pin():
    """Pin or remove a product from seasonal offers (admin override)."""
    db   = get_db()
    data = request.get_json()
    pid    = data.get("product_id","")
    action = data.get("action","pin")   # "pin" or "remove"
    now = datetime.datetime.utcnow()
    m   = now.month
    season = ("Summer"  if 3<=m<=5  else
              "Monsoon" if 6<=m<=9  else
              "Autumn"  if 10<=m<=11 else "Winter")

    db["seasonal_pins"].update_one(
        {"product_id": pid, "season": season},
        {"$set": {"product_id":pid,"season":season,"action":action,
                  "admin":session.get("admin_name"),"updated_at":now}},
        upsert=True
    )

    prod = db["products"].find_one({"product_id": pid}, {"name":1})
    name = prod.get("name","Product") if prod else "Product"
    verb = "pinned to" if action=="pin" else "removed from"
    return jsonify(success=True, message=f'"{name}" {verb} {season} seasonal offers.')


@admin_bp.route("/api/seasonal/unpin", methods=["POST"])
@admin_required
def seasonal_unpin():
    """Remove a pin/remove override — let ML decide again."""
    db  = get_db()
    pid = request.get_json().get("product_id","")
    now = datetime.datetime.utcnow()
    m   = now.month
    season = ("Summer"  if 3<=m<=5  else
              "Monsoon" if 6<=m<=9  else
              "Autumn"  if 10<=m<=11 else "Winter")
    db["seasonal_pins"].delete_one({"product_id":pid,"season":season})
    return jsonify(success=True, message="Override removed — ML will decide for this product.")


@admin_bp.route("/api/seasonal/history")
@admin_required
def seasonal_history():
    """
    Return redemption history grouped by season + product.
    Used for the season history section and pie charts.
    """
    db = get_db()
    pipeline = [
        {"$group": {
            "_id":          {"season":"$season","product_id":"$product_id","product_name":"$product_name"},
            "count":        {"$sum": 1},
            "total_revenue":{"$sum": "$price_paid"},
            "last_redeemed":{"$max": "$redeemed_at"},
        }},
        {"$sort": {"count": -1}}
    ]
    rows = list(db["seasonal_redemptions"].aggregate(pipeline))

    # Group by season
    by_season = {}
    for r in rows:
        s    = r["_id"]["season"]
        name = r["_id"]["product_name"]
        pid  = r["_id"]["product_id"]
        if s not in by_season:
            by_season[s] = {"season":s,"products":[],"total":0,"revenue":0}
        by_season[s]["products"].append({
            "product_id":  pid,
            "name":        name,
            "count":       r["count"],
            "revenue":     round(r["total_revenue"]),
        })
        by_season[s]["total"]   += r["count"]
        by_season[s]["revenue"] += round(r["total_revenue"])

    seasons_order = ["Summer","Monsoon","Autumn","Winter"]
    result = [by_season[s] for s in seasons_order if s in by_season]

    return jsonify(history=result)


@admin_bp.route("/api/seasonal/products")
@admin_required
def seasonal_all_products():
    """Return all active products for the pin selector dropdown."""
    db = get_db()
    prods = list(db["products"].find(
        {"is_active": {"$ne": False}},
        {"_id":0,"product_id":1,"name":1,"category_id":1,"price":1,"image_url":1}
    ).sort("name",1))
    return jsonify(products=prods)

# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS & REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/analytics")
@admin_required
def analytics():
    return render_template(
        "admin/analytics.html",
        admin_name  = session.get("admin_name", "Admin"),
        admin_role  = session.get("admin_role", "admin"),
        active_page = "analytics",
    )


@admin_bp.route("/api/analytics/summary")
@admin_required
def analytics_summary():
    """Top-level KPI cards for the analytics page."""
    db  = get_db()
    now = datetime.datetime.utcnow()

    total_revenue = sum(
        float(o.get("total_amount", 0))
        for o in db["orders"].find(
            {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
            {"total_amount": 1}
        )
    )

    total_orders    = db["orders"].count_documents({})
    paid_orders     = db["orders"].count_documents({"payment_status": "Paid", "order_status": {"$ne": "cancelled"}})
    total_customers = db["users"].count_documents({"role": {"$ne": "admin"}})

    # Repeat buyers
    pipeline = [
        {"$match": {"order_status": {"$ne": "cancelled"}}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
    ]
    order_counts   = list(db["orders"].aggregate(pipeline))
    repeat_buyers  = sum(1 for r in order_counts if r["count"] > 1)
    one_time       = sum(1 for r in order_counts if r["count"] == 1)

    # Payment split
    cod_count    = db["orders"].count_documents({"payment_method": "cod",    "order_status": {"$ne": "cancelled"}})
    online_count = db["orders"].count_documents({"payment_method": "online", "order_status": {"$ne": "cancelled"}})

    return jsonify(
        total_revenue    = round(total_revenue),
        total_orders     = total_orders,
        paid_orders      = paid_orders,
        total_customers  = total_customers,
        repeat_buyers    = repeat_buyers,
        one_time_buyers  = one_time,
        cod_count        = cod_count,
        online_count     = online_count,
    )


@admin_bp.route("/api/analytics/revenue-by-category")
@admin_required
def analytics_revenue_by_category():
    """Revenue and order count grouped by product category."""
    db = get_db()

    # Map product_id → category
    products   = {p["product_id"]: p for p in db["products"].find({}, {"_id":0,"product_id":1,"category_id":1,"name":1})}
    categories = {c["category_id"]: c["category_name"] for c in db["categories"].find({}, {"_id":0,"category_id":1,"category_name":1})}

    cat_revenue = {}
    cat_orders  = {}

    for order in db["orders"].find(
        {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
        {"items":1, "total_amount":1}
    ):
        for item in order.get("items", []):
            pid = item.get("product_id", "")
            prod = products.get(pid)
            if not prod:
                continue
            cid   = prod.get("category_id")
            cname = categories.get(cid, "Other")
            qty   = int(item.get("quantity", 1))
            rev   = float(item.get("price", 0)) * qty
            cat_revenue[cname] = cat_revenue.get(cname, 0) + rev
            cat_orders[cname]  = cat_orders.get(cname, 0)  + qty

    result = [
        {"category": k, "revenue": round(cat_revenue[k]), "units": cat_orders.get(k, 0)}
        for k in sorted(cat_revenue, key=lambda x: -cat_revenue[x])
    ]
    return jsonify(data=result)


@admin_bp.route("/api/analytics/revenue-by-product")
@admin_required
def analytics_revenue_by_product():
    """Top 10 products by revenue."""
    db = get_db()

    prod_revenue = {}
    prod_units   = {}

    for order in db["orders"].find(
        {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
        {"items": 1}
    ):
        for item in order.get("items", []):
            name = item.get("name", item.get("product_id", "Unknown"))
            qty  = int(item.get("quantity", 1))
            rev  = float(item.get("price", 0)) * qty
            prod_revenue[name] = prod_revenue.get(name, 0) + rev
            prod_units[name]   = prod_units.get(name, 0)   + qty

    top = sorted(prod_revenue, key=lambda x: -prod_revenue[x])[:10]
    result = [
        {"name": n, "revenue": round(prod_revenue[n]), "units": prod_units.get(n, 0)}
        for n in top
    ]
    return jsonify(data=result)


@admin_bp.route("/api/analytics/revenue-by-season")
@admin_required
def analytics_revenue_by_season():
    """Revenue per calendar season (uses booked_at date)."""
    db = get_db()

    SEASON_MAP = {1:"Winter",2:"Winter",3:"Summer",4:"Summer",5:"Summer",
                  6:"Monsoon",7:"Monsoon",8:"Monsoon",9:"Monsoon",
                  10:"Autumn",11:"Autumn",12:"Winter"}

    season_rev    = {}
    season_orders = {}

    for order in db["orders"].find(
        {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
        {"total_amount":1, "booked_at":1}
    ):
        booked = order.get("booked_at")
        if not booked or not hasattr(booked, "month"):
            continue
        season = SEASON_MAP.get(booked.month, "Other")
        year   = booked.year
        key    = f"{season} {year}"
        season_rev[key]    = season_rev.get(key, 0)    + float(order.get("total_amount", 0))
        season_orders[key] = season_orders.get(key, 0) + 1

    result = [
        {"season": k, "revenue": round(season_rev[k]), "orders": season_orders[k]}
        for k in sorted(season_rev)
    ]
    return jsonify(data=result)


@admin_bp.route("/api/analytics/seasonal-comparison")
@admin_required
def analytics_seasonal_comparison():
    """Compare the same season across two years, e.g. Summer 2025 vs Summer 2026."""
    db      = get_db()
    season  = request.args.get("season", "Summer")
    year1   = int(request.args.get("year1", datetime.datetime.utcnow().year - 1))
    year2   = int(request.args.get("year2", datetime.datetime.utcnow().year))

    SEASON_MONTHS = {
        "Summer":  [3, 4, 5],
        "Monsoon": [6, 7, 8, 9],
        "Autumn":  [10, 11],
        "Winter":  [12, 1, 2],
    }
    months = SEASON_MONTHS.get(season, [3, 4, 5])

    def season_stats(year):
        rev = 0; orders = 0; units = 0
        product_counts = {}
        for order in db["orders"].find(
            {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
            {"total_amount":1, "booked_at":1, "items":1}
        ):
            booked = order.get("booked_at")
            if not booked or not hasattr(booked, "year"):
                continue
            if booked.year != year or booked.month not in months:
                continue
            rev    += float(order.get("total_amount", 0))
            orders += 1
            for item in order.get("items", []):
                name = item.get("name", "Unknown")
                qty  = int(item.get("quantity", 1))
                units += qty
                product_counts[name] = product_counts.get(name, 0) + qty
        top_products = sorted(product_counts, key=lambda x: -product_counts[x])[:5]
        return {
            "revenue":      round(rev),
            "orders":       orders,
            "units":        units,
            "top_products": [{"name": n, "units": product_counts[n]} for n in top_products],
        }

    return jsonify(
        season = season,
        year1  = year1,
        year2  = year2,
        data1  = season_stats(year1),
        data2  = season_stats(year2),
    )


@admin_bp.route("/api/analytics/popular-by-season")
@admin_required
def analytics_popular_by_season():
    """Most popular products per season (all years combined)."""
    db = get_db()

    SEASON_MAP = {1:"Winter",2:"Winter",3:"Summer",4:"Summer",5:"Summer",
                  6:"Monsoon",7:"Monsoon",8:"Monsoon",9:"Monsoon",
                  10:"Autumn",11:"Autumn",12:"Winter"}

    data = {"Summer":{}, "Monsoon":{}, "Autumn":{}, "Winter":{}}

    for order in db["orders"].find(
        {"order_status": {"$ne": "cancelled"}},
        {"booked_at":1, "items":1}
    ):
        booked = order.get("booked_at")
        if not booked or not hasattr(booked, "month"):
            continue
        season = SEASON_MAP.get(booked.month)
        if not season:
            continue
        for item in order.get("items", []):
            name = item.get("name", "Unknown")
            qty  = int(item.get("quantity", 1))
            data[season][name] = data[season].get(name, 0) + qty

    result = {}
    for season, prods in data.items():
        top = sorted(prods, key=lambda x: -prods[x])[:5]
        result[season] = [{"name": n, "units": prods[n]} for n in top]

    return jsonify(data=result)


@admin_bp.route("/api/analytics/customer-retention")
@admin_required
def analytics_customer_retention():
    """Repeat vs one-time buyers with monthly cohort."""
    db = get_db()

    pipeline = [
        {"$match": {"order_status": {"$ne": "cancelled"}}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}, "name": {"$first": "$user_name"}}},
    ]
    records = list(db["orders"].aggregate(pipeline))

    one_time = [r for r in records if r["count"] == 1]
    repeat   = [r for r in records if r["count"] > 1]

    # Monthly new customers
    monthly = {}
    for order in db["orders"].find({}, {"user_id":1, "booked_at":1}):
        booked = order.get("booked_at")
        if not booked or not hasattr(booked, "month"):
            continue
        key = booked.strftime("%b %Y")
        if key not in monthly:
            monthly[key] = set()
        monthly[key].add(order.get("user_id", ""))

    monthly_list = [{"month": k, "new_customers": len(v)}
                    for k, v in sorted(monthly.items(),
                                       key=lambda x: datetime.datetime.strptime(x[0], "%b %Y"))][-12:]

    return jsonify(
        one_time_count = len(one_time),
        repeat_count   = len(repeat),
        monthly        = monthly_list,
        top_repeats    = sorted(
            [{"name": r.get("name","?"), "orders": r["count"]} for r in repeat],
            key=lambda x: -x["orders"]
        )[:10],
    )


@admin_bp.route("/api/analytics/payment-split")
@admin_required
def analytics_payment_split():
    """Payment method breakdown — online vs COD, monthly trend."""
    db = get_db()

    cod_total    = 0
    online_total = 0
    monthly      = {}

    for order in db["orders"].find(
        {"payment_status": "Paid", "order_status": {"$ne": "cancelled"}},
        {"payment_method":1, "total_amount":1, "booked_at":1}
    ):
        method = order.get("payment_method", "online")
        amount = float(order.get("total_amount", 0))
        booked = order.get("booked_at")

        if method == "cod":
            cod_total += amount
        else:
            online_total += amount

        if booked and hasattr(booked, "strftime"):
            key = booked.strftime("%b %Y")
            if key not in monthly:
                monthly[key] = {"month": key, "cod": 0, "online": 0}
            monthly[key][method if method == "cod" else "online"] += round(amount)

    monthly_list = sorted(monthly.values(),
                          key=lambda x: datetime.datetime.strptime(x["month"], "%b %Y"))[-12:]

    return jsonify(
        cod_total    = round(cod_total),
        online_total = round(online_total),
        monthly      = monthly_list,
    )


@admin_bp.route("/api/analytics/export-csv")
@admin_required
def analytics_export_csv():
    """Export orders data as CSV."""
    import csv, io
    from flask import Response

    db     = get_db()
    report = request.args.get("report", "orders")

    output = io.StringIO()
    writer = csv.writer(output)

    if report == "orders":
        writer.writerow(["Order ID","Customer","Email","Amount","Status","Payment","Date"])
        for o in db["orders"].find({}, {"_id":0}).sort("booked_at",-1):
            booked = o.get("booked_at","")
            if hasattr(booked,"strftime"):
                booked = booked.strftime("%d %b %Y %H:%M")
            writer.writerow([
                o.get("order_id",""), o.get("user_name",""), o.get("user_email",""),
                o.get("total_amount",""), o.get("order_status",""),
                o.get("payment_method",""), booked,
            ])
        filename = "chocobite_orders.csv"

    elif report == "products":
        writer.writerow(["Product","Category ID","Price","Stock","Rating","Visible"])
        for p in db["products"].find({}, {"_id":0}).sort("name",1):
            writer.writerow([
                p.get("name",""), p.get("category_id",""), p.get("price",""),
                p.get("stock_quantity",""), p.get("rating",""),
                "Yes" if p.get("is_active", True) else "No",
            ])
        filename = "chocobite_products.csv"

    elif report == "customers":
        writer.writerow(["Name","Email","Phone","Joined","Orders"])
        user_order_count = {}
        for o in db["orders"].find({}, {"user_id":1}):
            uid = o.get("user_id","")
            user_order_count[uid] = user_order_count.get(uid, 0) + 1
        for u in db["users"].find({"role":{"$ne":"admin"}}, {"_id":0}).sort("created_at",-1):
            joined = u.get("created_at","")
            if hasattr(joined,"strftime"):
                joined = joined.strftime("%d %b %Y")
            writer.writerow([
                u.get("name",""), u.get("email",""), u.get("phone",""),
                joined, user_order_count.get(u.get("user_id",""), 0),
            ])
        filename = "chocobite_customers.csv"

    else:
        return jsonify(error="Unknown report type"), 400

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ══════════════════════════════════════════════════════════════════════════════
#  ONE-TIME FIX — Visit /admin/fix-admin-credentials ONCE to update Atlas
#  Wipes admins collection, re-inserts with correct email + password,
#  removes admin@chocobite.com from users. DELETE AFTER RUNNING.
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/fix-admin-credentials")
def fix_admin_credentials():
    db = get_db()

    CORRECT_EMAIL    = "chocobite999x@gmail.com"
    CORRECT_PASSWORD = "ChocoBite@Admin2025"
    OLD_EMAIL        = "admin@chocobite.com"

    # 1. Drop entire admins collection and re-insert with correct credentials
    db["admins"].drop()
    db["admins"].insert_one({
        "admin_id":      str(uuid.uuid4()),
        "username":      "ChocoBite Admin",
        "email":         CORRECT_EMAIL,
        "password_hash": generate_password_hash(CORRECT_PASSWORD),
        "role":          "superadmin",
        "created_at":    datetime.datetime.utcnow(),
        "last_login":    None,
    })

    # 2. Remove admin@chocobite.com from users collection if it exists
    removed = db["users"].delete_one({"email": OLD_EMAIL})
    removed_count = removed.deleted_count

    return f"""
    <div style='font-family:sans-serif;max-width:500px;margin:60px auto;padding:28px;
                border:2px solid #d4820a;border-radius:14px;background:#111;color:#e8d5b0'>
        <h2 style='color:#f5c842;margin-bottom:16px'>&#10003; Admin credentials fixed!</h2>
        <p><b style='color:#d4820a'>Login Email:</b> {CORRECT_EMAIL}</p>
        <p style='margin-top:6px'><b style='color:#d4820a'>Password:</b> {CORRECT_PASSWORD}</p>
        <p style='margin-top:6px'><b style='color:#d4820a'>Role:</b> superadmin</p>
        <p style='margin-top:14px;color:#6fcf97'>&#10003; admins collection wiped and re-created.</p>
        <p style='color:#6fcf97'>&#10003; admin@chocobite.com removed from users: {removed_count} record(s) deleted.</p>
        <p style='margin-top:18px;padding:12px;background:#1a1a1a;border-radius:8px;
                  border:1px solid #8b1a1a;color:#e04040;font-size:13px'>
            &#9888; <b>Delete the fix_admin_credentials route from admin_routes.py now.</b>
        </p>
        <p style='margin-top:16px'>
            <a href='/admin/dashboard' style='color:#d4820a;font-weight:bold'>Go to Admin Dashboard &rarr;</a>
        </p>
    </div>
    """

# ══════════════════════════════════════════════════════════════════════════════
#  FEEDBACK & REVIEWS MODERATION
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/feedback")
@admin_required
def admin_feedback_page():
    return render_template(
        "admin/feedback.html",
        admin_name  = session.get("admin_name", "Admin"),
        admin_role  = session.get("admin_role", "admin"),
        active_page = "feedback",
    )


@admin_bp.route("/api/feedback/pending-count")
@admin_required
def feedback_pending_count():
    """Badge count: pending product reviews + unreplied general feedback."""
    db = get_db()
    pending_reviews   = db["product_reviews"].count_documents({"status": {"$in": ["pending", None]}})
    unreplied_general = db["feedback"].count_documents({"admin_reply": {"$exists": False}})
    return jsonify(count=pending_reviews + unreplied_general)


# ── General feedback ──────────────────────────────────────────────────────────

@admin_bp.route("/api/feedback/all")
@admin_required
def admin_feedback_all():
    """All general site feedback."""
    db    = get_db()
    items = list(db["feedback"].find({}, {"_id": 0}).sort("created_at", -1))
    for f in items:
        if "created_at" in f and hasattr(f["created_at"], "strftime"):
            f["created_raw"] = f["created_at"].isoformat()
            f["created_at"]  = f["created_at"].strftime("%d %b %Y, %I:%M %p")
        else:
            f["created_raw"] = ""
    return jsonify(items)


@admin_bp.route("/api/feedback/reply", methods=["POST"])
@admin_required
def admin_feedback_reply():
    """Save admin reply to general feedback."""
    db  = get_db()
    d   = request.get_json() or {}
    fid = d.get("feedback_id", "")
    reply = (d.get("reply") or "").strip()
    if not fid or not reply:
        return jsonify(success=False, message="Missing fields")
    result = db["feedback"].update_one(
        {"feedback_id": fid},
        {"$set": {"admin_reply": reply, "replied_at": datetime.datetime.utcnow()}}
    )
    if result.matched_count:
        return jsonify(success=True)
    return jsonify(success=False, message="Feedback not found")


# ── Product reviews moderation ────────────────────────────────────────────────

@admin_bp.route("/api/product-reviews/all")
@admin_required
def admin_product_reviews_all():
    """All product reviews with product name joined."""
    db      = get_db()
    reviews = list(db["product_reviews"].find({}, {"_id": 0}).sort("created_at", -1))
    # Join product names (use stored name, fallback to DB lookup)
    pid_set   = {r.get("product_id", "") for r in reviews if not r.get("product_name")}
    prod_map  = {}
    if pid_set:
        prod_map = {
            p["product_id"]: p.get("name", "")
            for p in db["products"].find({"product_id": {"$in": list(pid_set)}}, {"product_id":1,"name":1,"_id":0})
        }
    for r in reviews:
        if "created_at" in r and hasattr(r["created_at"], "strftime"):
            r["created_at"] = r["created_at"].strftime("%d %b %Y")
        if "status" not in r:
            r["status"] = "pending"
        if not r.get("product_name"):
            r["product_name"] = prod_map.get(r.get("product_id", ""), "")
    return jsonify(reviews)


@admin_bp.route("/api/product-reviews/moderate", methods=["POST"])
@admin_required
def admin_moderate_review():
    """Approve / reject / flag / hide a product review.
    Also re-computes the product weighted rating so only approved reviews count.
    """
    db  = get_db()
    d   = request.get_json() or {}
    rid = d.get("review_id", "")
    action = d.get("action", "")   # approved | rejected | flagged | hidden

    if action not in ("approved", "rejected", "flagged", "hidden"):
        return jsonify(success=False, message="Invalid action")
    if not rid:
        return jsonify(success=False, message="Missing review_id")

    review = db["product_reviews"].find_one({"review_id": rid})
    if not review:
        return jsonify(success=False, message="Review not found")

    db["product_reviews"].update_one(
        {"review_id": rid},
        {"$set": {"status": action, "moderated_at": datetime.datetime.utcnow()}}
    )

    # Recompute product weighted rating using only APPROVED reviews
    pid = review.get("product_id", "")
    if pid:
        _recompute_product_rating(db, pid)

    return jsonify(success=True)


@admin_bp.route("/api/product-reviews/reply", methods=["POST"])
@admin_required
def admin_review_reply():
    """Save admin reply to a product review. Stored in DB, shown on product page."""
    db  = get_db()
    d   = request.get_json() or {}
    rid = d.get("review_id", "")
    reply = (d.get("reply") or "").strip()
    if not rid or not reply:
        return jsonify(success=False, message="Missing fields")
    result = db["product_reviews"].update_one(
        {"review_id": rid},
        {"$set": {"admin_reply": reply, "replied_at": datetime.datetime.utcnow()}}
    )
    if result.matched_count:
        return jsonify(success=True)
    return jsonify(success=False, message="Review not found")


def _recompute_product_rating(db, product_id):
    """Weighted Bayesian average using only APPROVED reviews.
    rating = (R_user * N + R_base * W) / (N + W)   W=20
    """
    WEIGHT = 20
    product = db["products"].find_one({"product_id": product_id}, {"rating":1,"base_rating":1,"_id":0})
    if not product:
        return

    r_base = product.get("base_rating")
    if r_base is None:
        r_base = float(product.get("rating", 4.0))
        db["products"].update_one({"product_id": product_id}, {"$set": {"base_rating": r_base}})

    agg = list(db["product_reviews"].aggregate([
        {"$match": {"product_id": product_id, "status": "approved"}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}}
    ]))

    if not agg:
        # No approved reviews — revert to base rating
        new_rating = round(r_base, 1)
    else:
        r_user = float(agg[0]["avg"])
        n      = int(agg[0]["count"])
        new_rating = round((r_user * n + r_base * WEIGHT) / (n + WEIGHT), 1)

    db["products"].update_one({"product_id": product_id}, {"$set": {"rating": new_rating}})