"""
ChocoBite - Flask Backend
Run: python app.py
Then visit: http://localhost:5000/seed  (once, to populate the database)
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
try:
    from admin_routes import admin_bp
    _admin_bp_loaded = True
except Exception:
    _admin_bp_loaded = False
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import uuid, datetime, smtplib, re, random, string
try:
    from seasonal_recommender import get_seasonal_offers as _ml_seasonal
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = "chocobite_super_secret_key_change_this_in_production"
if _admin_bp_loaded:
    app.register_blueprint(admin_bp)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400 * 7
app.config["SESSION_COOKIE_SECURE"] = False

# ============================================================
#  MONGODB  — change port/host here if needed
# ============================================================
MONGO_HOST = "cluster-201.c05ha10.mongodb.net"
MONGO_PORT = 27017           # <-- CHANGE PORT HERE
MONGO_URI  = f"mongodb+srv://Shivani:prabshiv%40297@cluster-201.c05ha10.mongodb.net/chocobite"
# Atlas:  MONGO_URI = "mongodb+srv://user:pass@cluster.mongodb.net/chocobite"
DB_NAME = "chocobite"

client         = MongoClient(MONGO_URI)
db             = client[DB_NAME]
users_col      = db["users"]
categories_col = db["categories"]
products_col   = db["products"]
cart_col       = db["cart"]
orders_col     = db["orders"]
feedback_col        = db["feedback"]
product_reviews_col = db["product_reviews"]
payments_col        = db["payments"]
contacts_col   = db["contacts"]

# ============================================================
#  EMAIL  — put your Gmail + App Password here
# ============================================================
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USER = "chocobite999x@gmail.com"      # <-- YOUR EMAIL
EMAIL_PASS = "ufxaaliyzfkavugo"      # <-- APP PASSWORD

# ============================================================
#  RAZORPAY  — put your keys here
# ============================================================
# ── Dummy Payment Gateway (no real keys needed) ──────────────────────────────
DUMMY_PAYMENT_ENABLED = True   # Set False to disable online payment

# ─── UTILITIES ──────────────────────────────────────────────

def send_email(to, subject, html):
    # ── Common failure reasons ──────────────────────────────
    # 1. EMAIL_USER / EMAIL_PASS still have placeholder values → fill them above
    # 2. Using Gmail login password instead of App Password → generate one at
    #    myaccount.google.com → Security → App passwords
    # 3. 2-Step Verification not enabled on the Gmail account (required for App Passwords)
    # 4. Network/firewall blocking port 587
    if not EMAIL_USER or not EMAIL_PASS:
        print("[EMAIL SKIPPED] EMAIL_USER / EMAIL_PASS are still placeholders in app.py")
        print("  → Set real Gmail + App Password on lines 45-46 of app.py")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"ChocoBite <{EMAIL_USER}>"
        msg["To"]      = to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(EMAIL_USER, EMAIL_PASS)
            s.sendmail(EMAIL_USER, to, msg.as_string())
        print(f"[EMAIL SENT] {subject} → {to}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[EMAIL ERROR] Authentication failed — wrong email/password or App Password not set up")
        print("  → Go to myaccount.google.com → Security → App passwords → generate one")
        return False
    except smtplib.SMTPConnectError:
        print("[EMAIL ERROR] Could not connect to smtp.gmail.com:587 — check internet/firewall")
        return False
    except Exception as e:
        print(f"[EMAIL ERROR] {type(e).__name__}: {e}")
        return False

# ─── EMAIL TEMPLATES ──────────────────────────────────────────────────────────
# All emails use clean, readable plain-style HTML.
# Shared styles — keep inline so Gmail renders them correctly.

_EB  = "background:#0e0600"                        # email background (dark chocolate)
_EW  = "max-width:580px;margin:0 auto;font-family:Georgia,'Times New Roman',serif"
_HDR = "background:#1a0a00;padding:28px 36px 20px;text-align:center;border-bottom:3px solid #d4820a"
_BDY = "background:#1a0a00;padding:32px 36px"
_FTR = "background:#0e0600;padding:18px 36px;text-align:center;border-top:1px solid rgba(212,130,10,0.2)"
_BTN = "display:inline-block;background:#d4820a;color:#0e0600;font-family:Georgia,serif;font-size:15px;font-weight:bold;padding:13px 32px;border-radius:6px;text-decoration:none;letter-spacing:0.5px"
_H1  = "color:#f5c842;font-size:26px;font-weight:bold;margin:0 0 4px"
_P   = "color:#e8d5b0;font-size:16px;line-height:1.7;margin:0 0 16px"
_MUT = "color:#a07840;font-size:13px;line-height:1.6;margin:0"
_HR  = "border:none;border-top:1px solid rgba(212,130,10,0.2);margin:24px 0"


def _shell(header_html, body_html, footer_html=""):
    """Wraps content in the ChocoBite email shell."""
    return (
        f'<div style="{_EB};padding:24px 0">'
        f'<div style="{_EW}">'
        f'<div style="{_HDR}">{header_html}</div>'
        f'<div style="{_BDY}">{body_html}</div>'
        f'<div style="{_FTR}">{footer_html or _default_footer()}</div>'
        f'</div></div>'
    )


def _default_footer():
    return (
        f'<p style="{_MUT}">© ChocoBite &nbsp;|&nbsp; '
        f'<a href="http://localhost:5000" style="color:#d4820a;text-decoration:none">Visit our store</a> &nbsp;|&nbsp; '
        f'<a href="http://localhost:5000/contact" style="color:#d4820a;text-decoration:none">Contact Us</a></p>'
    )


def email_welcome(name):
    """
    Welcome / Login email.
    Subject : Welcome to ChocoBite! Your sweet journey starts here.
    """
    header = (
        f'<p style="color:#d4820a;font-size:13px;letter-spacing:2px;text-transform:uppercase;margin:0 0 8px">ChocoBite</p>'
        f'<h1 style="{_H1}">Welcome to ChocoBite!</h1>'
        f'<p style="color:#a07840;font-size:14px;margin:6px 0 0">Your sweet journey starts here 🍫</p>'
    )
    body = (
        f'<p style="{_P}">Hi <strong style="color:#f5c842">{name}</strong>,</p>'
        f'<p style="{_P}">We are thrilled to have you! You have successfully logged into your ChocoBite account.</p>'
        f'<p style="{_P}">Now that you are in, why not explore our latest Choco Beans or check out our new Sugar-Free collections? Your cart is ready and waiting for your next favourite treat.</p>'
        f'<hr style="{_HR}">'
        f'<p style="text-align:center;margin:28px 0">'
        f'<a href="http://localhost:5000/products" style="{_BTN}">Start Shopping</a>'
        f'</p>'
        f'<hr style="{_HR}">'
        f'<p style="{_MUT}">Stay sweet,<br><strong style="color:#d4820a">The ChocoBite Team</strong></p>'
    )
    return _shell(header, body)


def email_otp(name, otp):
    """
    Password reset OTP email.
    Subject : [Action Required] Your ChocoBite Reset Code: {otp}
    """
    header = (
        f'<p style="color:#d4820a;font-size:13px;letter-spacing:2px;text-transform:uppercase;margin:0 0 8px">ChocoBite Security</p>'
        f'<h1 style="{_H1}">[Action Required]</h1>'
        f'<p style="color:#a07840;font-size:14px;margin:6px 0 0">Password Reset Request</p>'
    )
    body = (
        f'<p style="{_P}">Hi <strong style="color:#f5c842">{name}</strong>,</p>'
        f'<p style="{_P}">We received a request to change your ChocoBite password. Use the verification code below to proceed.</p>'
        f'<div style="text-align:center;margin:32px 0">'
        f'<div style="display:inline-block;background:#2a1200;border:2px solid #d4820a;border-radius:10px;padding:20px 44px">'
        f'<p style="color:#a07840;font-size:12px;text-transform:uppercase;letter-spacing:2px;margin:0 0 8px">Your Reset Code</p>'
        f'<p style="color:#f5c842;font-size:42px;font-weight:bold;letter-spacing:12px;margin:0;font-family:monospace">{otp}</p>'
        f'<p style="color:#a07840;font-size:12px;margin:8px 0 0">Valid for 10 minutes</p>'
        f'</div></div>'
        f'<p style="{_P}">This code is valid for the next <strong>10 minutes</strong>.</p>'
        f'<p style="{_P}">If you did not request this change, please ignore this email or log in to your account to ensure your details are secure. <strong>We have not made any changes yet.</strong></p>'
        f'<hr style="{_HR}">'
        f'<p style="{_MUT}">Stay safe and sweet,<br><strong style="color:#d4820a">The ChocoBite Security Team</strong></p>'
    )
    return _shell(header, body)


def email_password_changed(name):
    """
    Password change success confirmation email.
    Subject : Security Update: Your ChocoBite Password Has Been Changed.
    """
    header = (
        f'<p style="color:#d4820a;font-size:13px;letter-spacing:2px;text-transform:uppercase;margin:0 0 8px">ChocoBite Security</p>'
        f'<h1 style="{_H1}">Password Updated!</h1>'
        f'<p style="color:#6fcf97;font-size:14px;margin:6px 0 0">✅ Your account is secure</p>'
    )
    body = (
        f'<p style="{_P}">Hi <strong style="color:#f5c842">{name}</strong>,</p>'
        f'<p style="{_P}"><strong>Success!</strong> Your password for ChocoBite has been updated. You can now log in using your new credentials to access your cart, order history, and those delicious chocolates you have been eyeing.</p>'
        f'<p style="text-align:center;margin:28px 0">'
        f'<a href="http://localhost:5000" style="{_BTN}">Log In Now</a>'
        f'</p>'
        f'<hr style="{_HR}">'
        f'<p style="{_P}">If you did not perform this action, please contact our support team immediately by clicking the <a href="http://localhost:5000/contact" style="color:#d4820a">Contact Us</a> link on our homepage.</p>'
        f'<hr style="{_HR}">'
        f'<p style="{_MUT}">Happy shopping!<br><strong style="color:#d4820a">The ChocoBite Team</strong></p>'
    )
    return _shell(header, body)


def email_wrap(title, body):
    """Legacy wrapper — used for order confirmation emails."""
    return (
        f'<div style="{_EB};padding:24px 0">'
        f'<div style="{_EW}">'
        f'<div style="{_HDR}">'
        f'<p style="color:#d4820a;font-size:13px;letter-spacing:2px;text-transform:uppercase;margin:0 0 8px">ChocoBite</p>'
        f'<h1 style="{_H1}">{title}</h1>'
        f'</div>'
        f'<div style="{_BDY}">{body}</div>'
        f'<div style="{_FTR}">{_default_footer()}</div>'
        f'</div></div>'
    )

def gen_otp():        return "".join(random.choices(string.digits, k=6))
def is_logged_in():   return "user_id" in session

# ============================================================
#  SEED ROUTE  — visit http://localhost:5000/seed once
#  This clears ALL products/categories and re-inserts fresh data.
# ============================================================
@app.route("/seed")
def seed():
    # Drop and re-create so stale data can't cause issues
    products_col.drop()
    categories_col.drop()

    # ── Categories ───────────────────────────────────────────
    categories_col.insert_many([
        {"category_id": 1, "category_name": "Cocoa Beans & Chips",
         "slug": "seeds",     "description": "Premium chocolate chips and cacao nibs"},
        {"category_id": 2, "category_name": "Choco Powder",
         "slug": "powder",    "description": "Pure cocoa and hot chocolate mixes"},
        {"category_id": 3, "category_name": "Flavoured Chocolates",
         "slug": "flavoured", "description": "Exotic flavour-infused premium chocolate bars"},
    ])

    now  = datetime.datetime.utcnow()
    i1   = "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500"
    i2   = "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500"
    i3   = "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500"
    i4   = "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500"

    # Extended product helper with all rich fields
    def p(cat, name, desc, price, img, sugarless, stock, rating="4.5",
          weight="150g", mrp=None, tagline="", why_this="",
          health_benefits="", pack_type="", price_per_100g=""):
        return {
            "product_id":      str(uuid.uuid4()),
            "category_id":     cat,
            "name":            name,
            "description":     desc,
            "price":           float(price),
            "mrp":             float(mrp) if mrp else float(price),
            "tagline":         tagline,
            "why_this":        why_this,
            "health_benefits": health_benefits,
            "pack_type":       pack_type,
            "price_per_100g":  price_per_100g,
            "image_url":       img,
            "is_sugarless":    sugarless,
            "stock_quantity":  stock,
            "rating":          float(rating),
            "weight":          weight,
            "created_at":      now,
        }

    # Shared health benefit text for each cocoa variety
    _criollo_health = (
        "A cup of your Criollo is more than a luxury — it's a ritual for your heart. "
        "With 40x the antioxidants of blueberries and a natural dose of the bliss molecule, "
        "it's the only indulgence that loves you back."
    )
    _forastero_health = (
        "The untamed power of the Amazon fuels your body with raw, robust energy of the "
        "Forastero bean. Known as the guardian of cocoa, this variety is a concentrated "
        "source of metabolic minerals and plant-based iron, designed to support physical "
        "stamina and bone strength. Its deep, intense profile is packed with potassium for "
        "muscle recovery and antioxidants that fight daily fatigue."
    )

    products = [

        # ══════════════════════════════════════════════════════════
        # CATEGORY 1 — COCOA BEANS & CHIPS  (slug: seeds)
        # All 11 products, all sugar-free
        # ══════════════════════════════════════════════════════════

        # ── Royal Criollo Cocoa ─────────────────────────────────

        # 1. Small pack — 150g
        p(1, "The Heirloom Batch",
          "A first encounter with the ancient bean. Royal Criollo cocoa — the rarest cacao "
          "on earth, prized for its delicate floral complexity and smooth finish.",
          499, i1, True, 40, "4.8", "150g",
          mrp=780,
          tagline="A first encounter with the ancient bean",
          why_this="Crafted for the modern alchemist, this 150g batch is the perfect size for "
                   "your private kitchen rituals. Enough to share, but crafted for you to keep.",
          health_benefits=_criollo_health,
          pack_type="Small",
          price_per_100g="₹499 / 100g"),

        # 2. Premium pack — 450g
        p(1, "The Royal Tribute",
          "The sacred drink of emperors, preserved for you. Royal Criollo cocoa at its most "
          "refined — our golden ratio pack for dedicated enthusiasts.",
          1899, i2, True, 25, "4.9", "450g",
          mrp=1900,
          tagline="The sacred drink of emperors, preserved for you",
          why_this="This is our golden ratio pack — the ideal volume for their lifestyle. "
                   "Designed for the dedicated enthusiast.",
          health_benefits=_criollo_health,
          pack_type="Premium",
          price_per_100g="₹422 / 100g"),

        # 3. Party pack — 1kg
        p(1, "The Sun Stone Collection",
          "Reviving the ritual of the ancient feast. A full kilogram of Royal Criollo cocoa "
          "for large gatherings — the luxury of sharing the world's finest bean.",
          3499, i4, True, 15, "4.7", "1000g",
          mrp=3600,
          tagline="Reviving the ritual of the ancient feast",
          why_this="A full kilogram for a large gathering (25+ people) to experience the luxury. "
                   "This bulk pack is crafted for those who believe the finest things in life "
                   "are meant to be enjoyed together.",
          health_benefits=_criollo_health,
          pack_type="Party",
          price_per_100g="₹349 / 100g"),

        # ── Grand Forastero Cocoa ───────────────────────────────

        # 4. Small pack — 150g
        p(1, "The Amazon Origin",
          "The raw spirit of the rainforest. Forastero originated in the Amazon basin — "
          "wild, untamed, and robustly chocolatey.",
          449, i1, True, 50, "4.5", "150g",
          mrp=460,
          tagline="The raw spirit of the rainforest",
          why_this="Forastero originated in the Amazon basin. This name highlights its wild, "
                   "untamed roots.",
          health_benefits=_forastero_health,
          pack_type="Small",
          price_per_100g="₹299 / 100g"),

        # 5. Premium pack — 450g
        p(1, "The Earth's Harvest",
          "Bold, deep, and timelessly chocolate. Forastero is famous for its classic, strong "
          "chocolatey flavour profile — reliable and naturally strong.",
          999, i2, True, 30, "4.6", "450g",
          mrp=1010,
          tagline="Bold, deep, and timelessly chocolate",
          why_this="Forastero is famous for its classic, strong chocolatey flavour profile. "
                   "This name suggests reliability and natural strength.",
          health_benefits=_forastero_health,
          pack_type="Premium",
          price_per_100g="₹222 / 100g"),

        # 6. Party pack — 1kg
        p(1, "The Foundation Batch",
          "The soul of the world's cocoa ritual. Since most of the world's chocolate is made "
          "from Forastero, this batch honours its role as the essential base.",
          1849, i4, True, 18, "4.4", "1000g",
          mrp=1900,
          tagline="The soul of the world's cocoa ritual",
          why_this="Since most of the world's chocolate is made from Forastero, this name "
                   "honours its role as the essential base for all chocolate lovers.",
          health_benefits=_forastero_health,
          pack_type="Party",
          price_per_100g="₹184 / 100g"),

        # ── Cocoa Chips — The Sacred Gems ──────────────────────

        # 7. Classic chips — 250g
        p(1, "Obsidian Droplets",
          "The fundamental spark of every creation. High-stability cocoa chips that hold "
          "their peak flavour under high heat — a baker's essential.",
          599, i3, True, 55, "4.7", "250g",
          mrp=599,
          tagline="The fundamental spark of every creation",
          why_this="These are high-stability chips that hold their peak flavour under high heat. "
                   "Perfect for the purist baker who wants a consistent, deep cocoa melt in "
                   "every bite of a cookie or muffin.",
          health_benefits="Pure cocoa power in every drop — packed with antioxidants and "
                          "flavonoids that support heart health and mental clarity.",
          pack_type="Premium",
          price_per_100g="₹239 / 100g"),

        # 8. Round chips — 250g
        p(1, "Lunar Orbs",
          "Perfectly balanced, infinitely smooth. Spherical cocoa chips for an even, "
          "melt-in-the-mouth experience. Ideal for professional garnishing.",
          649, i1, True, 45, "4.6", "250g",
          mrp=649,
          tagline="Perfectly balanced, infinitely smooth",
          why_this="The spherical shape allows for a more even melt-in-the-mouth experience. "
                   "Ideal for professional garnishing or panning (coating nuts), giving your "
                   "desserts a polished, high-end look.",
          health_benefits="Pure cocoa power in every drop — packed with antioxidants and "
                          "flavonoids that support heart health and mental clarity.",
          pack_type="Premium",
          price_per_100g="₹259 / 100g"),

        # 9. Heart chips — 250g
        p(1, "Ixchel's Devotion",
          "The language of the heart, etched in cocoa. Heart-shaped premium cocoa chips "
          "for anniversary baking, Valentine's gifts and luxury toppings.",
          699, i2, True, 40, "4.8", "250g",
          mrp=699,
          tagline="The language of the heart, etched in cocoa",
          why_this="These are your emotional premium product. Perfect for anniversary baking, "
                   "Valentine's Day gifts, or luxury topping for a loved one's morning bowl. "
                   "They turn a simple brownie into a romantic gesture.",
          health_benefits="Pure cocoa power in every drop — packed with antioxidants and "
                          "flavonoids that support heart health and mental clarity.",
          pack_type="Premium",
          price_per_100g="₹279 / 100g"),

        # 10. Star chips — 250g
        p(1, "Celestial Spark",
          "A taste of the heavens in every morsel. Star-shaped cocoa chips with sharp edges "
          "for unique snap and texture — the best choice for festive decorating.",
          699, i3, True, 38, "4.7", "250g",
          mrp=699,
          tagline="A taste of the heavens in every morsel",
          why_this="The sharp edges of the star shape provide a unique snap and texture. "
                   "They are the best choice for decorating festive cakes or topping smoothie "
                   "bowls where visual wow-factor is the priority.",
          health_benefits="Pure cocoa power in every drop — packed with antioxidants and "
                          "flavonoids that support heart health and mental clarity.",
          pack_type="Premium",
          price_per_100g="₹279 / 100g"),

        # 11. Mixed shapes — 500g
        p(1, "The Cosmos Medley",
          "The complete map of ancient chocolate artistry. All four cocoa chip shapes in one "
          "500g pack — the ultimate creative baker's toolkit.",
          1299, i4, True, 30, "4.9", "500g",
          mrp=1299,
          tagline="The complete map of ancient chocolate artistry",
          why_this="This is your all-in-one solution. It offers the best value and variety for "
                   "creative bakers who want to experiment with different textures and shapes "
                   "in a single recipe. It saves the customer from buying four separate packs.",
          health_benefits="Pure cocoa power in every drop — packed with antioxidants and "
                          "flavonoids that support heart health and mental clarity.",
          pack_type="Premium",
          price_per_100g="₹259 / 100g"),

        # ══════════════════════════════════════════════════════════
        # CATEGORY 2 — CHOCO POWDER
        # ══════════════════════════════════════════════════════════
        p(2,"GloryBean Cacao Powder",
          "Cold-pressed raw cacao powder from GloryBean's single-origin farms. "
          "Intensely chocolatey, packed with antioxidants. No sugar, no additives.",
          249, i3, True, 50, "4.7", "200g"),

        p(2,"GloryBean Hot Mix",
          "GloryBean's premium instant hot chocolate mix. Rich cocoa, creamy milk powder "
          "and a hint of vanilla — just add hot water or milk.",
          269, i4, False, 55, "4.6", "250g"),

        p(2,"Dutch Cocoa Powder",
          "Smooth Dutch-processed cocoa powder with deep colour and mild flavour. "
          "Ideal for hot chocolate, cakes and brownies.",
          189, i3, False, 60, "4.6", "250g"),

        p(2,"Raw Organic Cacao Powder",
          "Cold-pressed raw cacao with antioxidants intact. Intense natural chocolate "
          "flavour, no sugar — straight from the cacao pod.",
          229, i2, True, 40, "4.4", "200g"),

        p(2,"Sugar-Free Cocoa Mix",
          "Pure unsweetened cocoa powder. Perfect for diabetics and health-conscious bakers. "
          "No fillers, no sugar, no compromise.",
          209, i1, True, 35, "4.3", "200g"),

        p(2,"Premium Hot Choco Mix",
          "Instant gourmet hot chocolate mix with milk powder, vanilla and premium cocoa. "
          "One scoop — pure comfort in a mug.",
          249, i4, False, 55, "4.8", "300g"),

        # ══════════════════════════════════════════════════════════
        # CATEGORY 3 — FLAVOURED CHOCOLATES
        # ══════════════════════════════════════════════════════════
        p(3,"GloryBean Classic Bar",
          "GloryBean's iconic smooth milk chocolate bar. Whole milk, premium cocoa butter "
          "and generous cocoa solids. Melts perfectly on your tongue.",
          229, i2, False, 40, "4.8", "100g"),

        p(3,"GloryBean Hazel Crunch",
          "Whole roasted hazelnuts embedded in GloryBean's 60% dark chocolate. "
          "Stunning crunch-to-melt contrast.",
          299, i1, False, 30, "4.9", "100g"),

        p(3,"Classic Milk Choco Bar",
          "Smooth, creamy classic milk chocolate bar made with full-cream milk and rich cocoa.",
          199, i2, False, 40, "4.5", "100g"),

        p(3,"Belgian Dark Sugar Delight",
          "Premium 55% dark chocolate bar sweetened with pure cane sugar for a balanced "
          "bittersweet taste.",
          279, i1, False, 28, "4.7", "100g"),

        p(3,"Salted Caramel Dark",
          "Rich dark chocolate bar with a gooey salted caramel centre. "
          "An indulgent treat that balances sweet, salty and bitter.",
          299, i2, False, 25, "4.9", "100g"),

        p(3,"Mint Dark Chocolate",
          "Refreshing peppermint infused into 65% dark chocolate. "
          "Cool and intense — a timeless combination.",
          279, i1, False, 30, "4.5", "100g"),

        p(3,"Sugar-Free Dark 85%",
          "Intensely dark 85% cocoa bar sweetened only with stevia. "
          "For true dark chocolate lovers who skip the sugar.",
          319, i4, True, 22, "4.6", "100g"),

        p(3,"Orange Zest Chocolate",
          "Real orange peel pieces in silky dark chocolate. A fruity, zesty delight.",
          269, i4, False, 15, "4.4", "100g"),
    ]

    products_col.insert_many(products)

    # Create indexes
    try:
        products_col.create_index([("product_id", 1)], unique=True)
        products_col.create_index([("category_id", 1)])
        products_col.create_index([("is_sugarless", 1)])
        categories_col.create_index([("slug", 1)], unique=True)
        categories_col.create_index([("category_id", 1)], unique=True)
    except Exception:
        pass

    total = products_col.count_documents({})
    cats  = categories_col.count_documents({})
    return f"""
    <html><body style="font-family:monospace;background:#111;color:#6fcf97;padding:40px">
    <h2>✅ Seed complete!</h2>
    <p>Categories inserted: <b>{cats}</b></p>
    <p>Products inserted: <b>{total}</b></p>
    <br>
    <p>GloryBean products in Cat 1 (Choco Beans): <b>
        {products_col.count_documents({"category_id":1,"name":{"$regex":"GloryBean"}})}
    </b></p>
    <p>Total Cat 1 products: <b>{products_col.count_documents({"category_id":1})}</b></p>
    <p>Total Cat 2 products: <b>{products_col.count_documents({"category_id":2})}</b></p>
    <p>Total Cat 3 products: <b>{products_col.count_documents({"category_id":3})}</b></p>
    <br>
    <a href="/" style="color:#f5c842">→ Go to website</a>
    </body></html>"""


# ─── PAGE ROUTES ────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/products")
def products_page():
    return render_template("products.html")

@app.route("/product/<product_id>")
def product_detail(product_id):
    p = products_col.find_one({"product_id": product_id})
    if not p: return redirect(url_for("products_page"))
    p.pop("_id", None)
    cat = categories_col.find_one({"category_id": p.get("category_id")})
    p["category_name"] = cat["category_name"] if cat else "Chocolate"
    return render_template("product_detail.html", product=p)

@app.route("/about-product/<product_id>")
def about_product(product_id):
    p = products_col.find_one({"product_id": product_id})
    if not p: return redirect(url_for("products_page"))
    p.pop("_id", None)
    cat = categories_col.find_one({"category_id": p.get("category_id")})
    p["category_name"] = cat["category_name"] if cat else "Chocolate"
    p["slug"]          = cat["slug"]           if cat else "flavoured"
    return render_template("about_product.html", product=p)

@app.route("/cart")
def cart_page():
    return render_template("cart.html")

@app.route("/about")
def about():    return render_template("about.html")

@app.route("/contact")
def contact():  return render_template("contact.html")

@app.route("/feedback")
def feedback(): return render_template("feedback.html")


# ─── AUTH API ────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    d         = request.get_json()
    full_name = (d.get("full_name") or d.get("name") or "").strip()
    email     = d.get("email","").strip().lower()
    password  = d.get("password","")
    phone     = d.get("phone","").strip()
    address   = d.get("address","").strip()

    if not all([full_name, email, password]):
        return jsonify(success=False, message="Name, email and password required")
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return jsonify(success=False, message="Invalid email")
    if len(password) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")
    if users_col.find_one({"email": email}):
        return jsonify(success=False, message="Email already registered")

    uid = str(uuid.uuid4())
    users_col.insert_one({
        "user_id": uid, "full_name": full_name, "email": email,
        "password_hash": generate_password_hash(password),
        "otp_code": None, "otp_expires": None, "is_verified": False,
        "phone": phone or None, "address": address or None,
        "created_at": datetime.datetime.utcnow()
    })
    send_email(email,
        "Welcome to ChocoBite! Your sweet journey starts here.",
        email_welcome(full_name))
    session.update({"user_id": uid, "user_name": full_name, "user_email": email})
    return jsonify(success=True, message="Registration successful!", name=full_name)


@app.route("/api/login", methods=["POST"])
def login():
    d     = request.get_json()
    email = d.get("email","").strip().lower()
    pw    = d.get("password","").strip()

    # ── Check admin collection first ─────────────────────────────────────────
    admin = db["admins"].find_one({"email": email})
    if admin and check_password_hash(admin.get("password_hash", ""), pw):
        session["admin_id"]          = admin["admin_id"]
        session["admin_name"]        = admin.get("username", "Admin")
        session["admin_role"]        = admin.get("role", "admin")
        session["admin_last_active"] = datetime.datetime.utcnow().isoformat()
        db["admins"].update_one({"admin_id": admin["admin_id"]},
                                {"$set": {"last_login": datetime.datetime.utcnow()}})
        # Send admin login notification email
        try:
            admin_email = admin.get("email", EMAIL_USER)
            body = (
                f"<p style='color:#e8d5b0;font-size:15px'>Hello <strong style='color:#f5c842'>"
                f"{admin.get('username','Admin')}</strong>,</p>"
                f"<p style='color:#e8d5b0;font-size:15px;margin-top:12px'>"
                f"A successful admin login was recorded on your ChocoBite admin portal.</p>"
                f"<p style='color:#a07840;font-size:13px;margin-top:10px'>"
                f"Time: {datetime.datetime.utcnow().strftime('%d %b %Y, %I:%M %p UTC')}<br>"
                f"If this was not you, change your password immediately.</p>"
            )
            send_email(admin_email, "ChocoBite Admin — Login Successful 🔐",
                       email_wrap("Admin Login Alert", body))
        except Exception:
            pass
        return jsonify(success=True, message="Admin login successful!",
                       name=admin.get("username", "Admin"),
                       is_admin=True, redirect="/admin/dashboard")

    # ── Regular user login ────────────────────────────────────────────────────
    user = users_col.find_one({"email": email})
    if not user or not check_password_hash(user["password_hash"], pw):
        return jsonify(success=False, message="Invalid email or password")
    session.update({"user_id": user["user_id"], "user_name": user["full_name"], "user_email": email})
    send_email(email,
        "Welcome to ChocoBite! Your sweet journey starts here.",
        email_welcome(user["full_name"]))
    return jsonify(success=True, message="Login successful!", name=user["full_name"], is_admin=False)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear(); return jsonify(success=True)


@app.route("/api/forgot-password", methods=["POST"])
def forgot_password():
    email = request.get_json().get("email","").strip().lower()
    user  = users_col.find_one({"email": email})
    if not user: return jsonify(success=False, message="Email not found")
    otp = gen_otp()
    exp = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    users_col.update_one({"email": email}, {"$set": {"otp_code": otp, "otp_expires": exp}})
    print(f"[OTP] Generated OTP {otp} for {email}, expires at {exp}")
    email_sent = send_email(email,
        f"[Action Required] Your ChocoBite Reset Code: {otp}",
        email_otp(user["full_name"], otp))
    if not email_sent:
        # Email failed — still return OTP in message for dev/testing
        print(f"[OTP] Email failed. OTP for {email}: {otp}")
    return jsonify(success=True, message="OTP sent to your email")


@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    d     = request.get_json()
    email = d.get("email", "").strip().lower()
    otp   = d.get("otp", "").strip()
    npw   = d.get("new_password", "")

    # Validate inputs
    if not email: return jsonify(success=False, message="Email is required")
    if not otp:   return jsonify(success=False, message="OTP is required")
    if len(npw) < 6: return jsonify(success=False, message="Password must be at least 6 characters")

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify(success=False, message="No account found with this email")

    # Check OTP exists
    stored_otp = user.get("otp_code")
    if not stored_otp:
        return jsonify(success=False, message="No OTP requested. Please request a new one.")

    # Check OTP match
    if stored_otp != otp:
        return jsonify(success=False, message="Incorrect OTP. Please check and try again.")

    # Check expiry — otp_expires is stored as UTC datetime
    exp = user.get("otp_expires")
    if exp:
        now = datetime.datetime.utcnow()
        # Strip timezone info if present to allow naive comparison
        if hasattr(exp, "tzinfo") and exp.tzinfo is not None:
            exp = exp.replace(tzinfo=None)
        if now > exp:
            # Clear expired OTP
            users_col.update_one({"email": email}, {"$unset": {"otp_code": "", "otp_expires": ""}})
            return jsonify(success=False, message="OTP has expired. Please request a new one.")

    # Strip whitespace, re-validate
    npw = npw.strip()
    if len(npw) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")
    # Update by _id to guarantee match, split into two ops
    new_hash = generate_password_hash(npw, method='pbkdf2:sha256')
    result = users_col.update_one({"_id": user["_id"]}, {"$set": {"password_hash": new_hash}})
    users_col.update_one({"_id": user["_id"]}, {"$unset": {"otp_code": "", "otp_expires": ""}})
    print(f"[PASSWORD RESET] email={email} matched={result.matched_count} modified={result.modified_count}")
    send_email(email,
        "Security Update: Your ChocoBite Password Has Been Changed.",
        email_password_changed(user["full_name"]))
    return jsonify(success=True, message="Password reset successful! You can now login.")


@app.route("/api/session-status")
def session_status():
    if is_logged_in():
        return jsonify(logged_in=True, name=session.get("user_name"), email=session.get("user_email"))
    return jsonify(logged_in=False)


# ─── CATEGORIES API ─────────────────────────────────────────

@app.route("/api/categories")
def get_categories():
    cats = list(categories_col.find({}, {"_id": 0}).sort("category_id", 1))
    return jsonify(cats)


# ─── PRODUCTS API ───────────────────────────────────────────

@app.route("/api/products")
def get_products():
    slug      = request.args.get("category", "").strip()
    sugarless = request.args.get("sugarless", "all").strip().lower()
    search    = request.args.get("search", "").strip()

    query = {}

    # When search term present, ignore category — search across ALL products
    # so "GloryBean Original" finds it regardless of which tab is active
    if search:
        query["$or"] = [
            {"name":        {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]
    else:
        # No search — filter by category tab
        if slug:
            cat = categories_col.find_one({"slug": slug})
            if cat:
                query["category_id"] = cat["category_id"]

    # Sugar filter always applies regardless of search/category
    if sugarless == "true":
        query["is_sugarless"] = True
    elif sugarless == "false":
        query["is_sugarless"] = False

    # Exclude inactive products from user-facing store
    query["is_active"] = {"$ne": False}
    prods = list(products_col.find(query, {"_id": 0}))

    # Attach launch offer status to each product for frontend display
    now = datetime.datetime.utcnow()
    for p in prods:
        lo = p.get("launch_offer")
        if lo and lo.get("active"):
            expires = lo.get("expires_at")
            buyers  = lo.get("buyers_count", 0)
            max_b   = lo.get("max_buyers", 10)
            # Deactivate expired or fully redeemed offers
            if (expires and expires < now) or buyers >= max_b:
                p["launch_offer_active"]  = False
            else:
                p["launch_offer_active"]  = True
                p["launch_offer_price"]   = lo.get("offer_price")
                p["launch_offer_pct"]     = lo.get("discount_pct", 50)
                p["launch_offer_left"]    = max_b - buyers
                p["launch_offer_expires"] = expires.isoformat() if expires else None
        else:
            p["launch_offer_active"] = False
    return jsonify(prods)


@app.route("/api/product/<product_id>")
def get_product_api(product_id):
    p = products_col.find_one({"product_id": product_id}, {"_id": 0})
    if not p: return jsonify(error="Not found"), 404
    cat = categories_col.find_one({"category_id": p.get("category_id")}, {"_id": 0})
    p["category_name"] = cat["category_name"] if cat else ""
    return jsonify(p)


# ─── CART API ───────────────────────────────────────────────

@app.route("/api/cart/add", methods=["POST"])
def cart_add():
    if not is_logged_in():
        return jsonify(success=False, message="Please login first")
    d          = request.get_json()
    product_id = d.get("product_id")
    quantity   = max(1, int(d.get("quantity", 1)))

    product = products_col.find_one({"product_id": product_id})
    if not product: return jsonify(success=False, message="Product not found")
    if product.get("stock_quantity", 0) <= 0:
        return jsonify(success=False, message="Out of stock")

    user_id  = session["user_id"]
    existing = cart_col.find_one({"user_id": user_id, "product_id": product_id, "status": "active"})
    if existing:
        cart_col.update_one({"cart_id": existing["cart_id"]}, {"$inc": {"quantity": quantity}})
    else:
        cart_col.insert_one({
            "cart_id":    str(uuid.uuid4()), "user_id": user_id,
            "product_id": product_id, "quantity": quantity, "status": "active",
            "added_at":   datetime.datetime.utcnow(),
            "_name":  product["name"], "_price": product["price"],
            "_image": product.get("image_url",""),
        })
    return jsonify(success=True, message="Added to cart 🛒")


@app.route("/api/cart")
def cart_get():
    if not is_logged_in(): return jsonify(success=False, cart=[])
    items = list(cart_col.find({"user_id": session["user_id"], "status": "active"}, {"_id": 0}))
    for item in items:
        p = products_col.find_one({"product_id": item["product_id"]}, {"_id": 0})
        if p:
            item["name"] = p["name"]; item["price"] = p["price"]
            item["image_url"] = p.get("image_url",""); item["stock_quantity"] = p.get("stock_quantity",0)
    return jsonify(success=True, cart=items)


@app.route("/api/cart/update", methods=["POST"])
def cart_update():
    if not is_logged_in(): return jsonify(success=False)
    d = request.get_json(); cart_id = d.get("cart_id"); qty = int(d.get("quantity",1))
    if qty <= 0:
        cart_col.delete_one({"cart_id": cart_id, "user_id": session["user_id"]})
    else:
        cart_col.update_one({"cart_id": cart_id, "user_id": session["user_id"]}, {"$set": {"quantity": qty}})
    return jsonify(success=True)


@app.route("/api/cart/remove", methods=["POST"])
def cart_remove():
    if not is_logged_in(): return jsonify(success=False)
    cart_col.delete_one({"cart_id": request.get_json().get("cart_id"), "user_id": session["user_id"]})
    return jsonify(success=True)


@app.route("/api/cart/count")
def cart_count():
    if not is_logged_in(): return jsonify(count=0)
    res = list(cart_col.aggregate([
        {"$match": {"user_id": session["user_id"], "status": "active"}},
        {"$group": {"_id": None, "total": {"$sum": "$quantity"}}}
    ]))
    return jsonify(count=res[0]["total"] if res else 0)


# ─── ORDERS API ─────────────────────────────────────────────

def _place_order(items, address, total, method, rz_oid=None, rz_pid=None):
    oid = str(uuid.uuid4())
    now = datetime.datetime.utcnow()
    eta = now + datetime.timedelta(days=7)   # 7-day delivery estimate
    ship_by = now + datetime.timedelta(days=2)  # admin must ship within 2 days
    orders_col.insert_one({
        "order_id": oid, "user_id": session["user_id"],
        "user_name": session["user_name"], "user_email": session["user_email"],
        "items": items, "total_amount": float(total),
        "payment_method": method, "order_status": "processing",
        "payment_status": "Paid" if method == "online" else "Pending (COD)",
        "delivery_address": address,
        "booked_at": now, "estimated_arrival": eta,
        "ship_by": ship_by,
        "razorpay_order_id": rz_oid, "razorpay_payment_id": rz_pid,
    })
    # ── Track seasonal offer redemptions ─────────────────────────────────────
    for item in items:
        if item.get("is_seasonal_offer"):
            db["seasonal_redemptions"].insert_one({
                "redemption_id": str(uuid.uuid4()),
                "order_id":      oid,
                "user_id":       session.get("user_id",""),
                "user_name":     session.get("user_name",""),
                "product_id":    item.get("product_id",""),
                "product_name":  item.get("name",""),
                "season":        item.get("season_name",""),
                "discount_pct":  item.get("discount_pct", 0),
                "price_paid":    float(item.get("price", 0)),
                "redeemed_at":   now,
            })

    # ── Notify admin of new order
    try:
        item_rows = "".join(
            f"<tr><td style='padding:6px 10px;color:#e8d5b0'>{i['name']} x{i['quantity']}</td>"
            f"<td style='padding:6px 10px;color:#f5c842;text-align:right'>&#8377;{i['price']}</td></tr>"
            for i in items)
        ship_by_str = ship_by.strftime('%d %b %Y %I:%M %p UTC')
        eta_str = eta.strftime('%d %b %Y')
        body = (
            f"<p style='color:#e8d5b0;font-size:15px'>A new order has been placed on ChocoBite!</p>"
            f"<table style='width:100%;border-collapse:collapse;margin:14px 0'>{item_rows}</table>"
            f"<p style='color:#e8d5b0;font-size:14px'>"
            f"<strong style='color:#d4820a'>Order ID:</strong> <code style='color:#f5c842'>{oid}</code><br>"
            f"<strong style='color:#d4820a'>Customer:</strong> {session.get('user_name')} ({session.get('user_email')})<br>"
            f"<strong style='color:#d4820a'>Total:</strong> &#8377;{total}<br>"
            f"<strong style='color:#d4820a'>Payment:</strong> {'Online' if method=='online' else 'COD'}<br>"
            f"<strong style='color:#e04040'>&#9888; Ship by:</strong> {ship_by_str}<br>"
            f"<strong style='color:#d4820a'>Deliver by:</strong> {eta_str}</p>"
            f"<p style='color:#a07840;font-size:13px;margin-top:10px'>"
            f"Log in to the admin portal to process this order.</p>"
        )
        send_email(EMAIL_USER, f"&#127851; New Order #{oid[:8]} — Ship by {ship_by_str}",
                   email_wrap("New Order Received", body))
    except Exception as e:
        print(f"[ADMIN NOTIFY] {e}")
    for item in items:
        products_col.update_one({"product_id": item["product_id"]},
                                {"$inc": {"stock_quantity": -item["quantity"]}})
        # If this item used a launch offer, increment buyer count
        if item.get("used_launch_offer"):
            now_ts = datetime.datetime.utcnow()
            p = products_col.find_one({"product_id": item["product_id"]})
            if p:
                lo = p.get("launch_offer", {})
                new_count = lo.get("buyers_count", 0) + item.get("quantity", 1)
                updates = {"launch_offer.buyers_count": new_count}
                # Auto-deactivate if max buyers reached or expired
                if new_count >= lo.get("max_buyers", 10) or                    (lo.get("expires_at") and lo["expires_at"] < now_ts):
                    updates["launch_offer.active"] = False
                products_col.update_one(
                    {"product_id": item["product_id"]},
                    {"$set": updates}
                )
    cart_col.delete_many({"user_id": session["user_id"], "status": "active"})

    rows = "".join(
        f"<tr style='border-bottom:1px solid #d4820a33'>"
        f"<td style='padding:10px 12px;color:#fff;font-size:14px'>{i['name']}</td>"
        f"<td style='padding:10px 12px;color:#fff;font-size:14px;text-align:center'>{i['quantity']}</td>"
        f"<td style='padding:10px 12px;color:#f5c842;font-size:14px;text-align:right;font-weight:bold'>&#8377;{i['price']}</td>"
        f"</tr>"
        for i in items)
    body = (
        f"<p style='color:#e8d5b0;font-size:15px;margin:0 0 20px'>"
        f"Hi <strong style='color:#f5c842'>{session['user_name']}</strong>, your order is confirmed!</p>"
        f"<table style='width:100%;border-collapse:collapse;background:#2a1200;"
        f"border:1px solid #d4820a44;border-radius:8px;overflow:hidden'>"
        f"<tr style='background:#3d1c00'>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:13px;text-align:left'>Product</th>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:13px;text-align:center'>Qty</th>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:13px;text-align:right'>Price</th>"
        f"</tr>{rows}</table>"
        f"<p style='color:#e8d5b0;font-size:15px;margin:20px 0 8px'>"
        f"<strong style='color:#d4820a'>Total:</strong> "
        f"<span style='color:#f5c842;font-weight:bold'>&#8377;{total}</span>"
        f"&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"<strong style='color:#d4820a'>Payment:</strong> "
        f"<span style='color:#fff'>{'Cash on Delivery' if method=='cod' else 'Online'}</span></p>"
        f"<p style='color:#e8d5b0;font-size:15px;margin:0 0 8px'>"
        f"<strong style='color:#d4820a'>Estimated Delivery:</strong> "
        f"<span style='color:#fff'>{eta.strftime('%d %b %Y')}</span></p>"
        f"<p style='color:#e8d5b0;font-size:15px;margin:0'>"
        f"<strong style='color:#d4820a'>Order ID:</strong> "
        f"<code style='color:#f5c842;font-size:13px;word-break:break-all'>{oid}</code></p>"
    )
    send_email(session["user_email"], "ChocoBite — Order Confirmed 🍫",
               email_wrap("Order Confirmed 🎉", body))
    return oid


@app.route("/api/order/cod", methods=["POST"])
def order_cod():
    if not is_logged_in(): return jsonify(success=False, message="Please login first")
    d = request.get_json()
    if not d.get("items"):             return jsonify(success=False, message="No items")
    if not d.get("address","").strip(): return jsonify(success=False, message="Enter delivery address")

    # ── Duplicate guard: block same user placing identical order within 30s ──
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=30)
    recent = orders_col.find_one({
        "user_id": session["user_id"],
        "booked_at": {"$gte": cutoff},
        "payment_method": "cod",
        "total_amount": float(d.get("total", 0))
    })
    if recent:
        return jsonify(success=True, order_id=recent["order_id"],
                       message="Order placed! Confirmation email sent.")

    oid = _place_order(d["items"], d["address"], d["total"], "cod")
    return jsonify(success=True, order_id=oid, message="Order placed! Confirmation email sent.")


@app.route("/payment")
def payment_page():
    """Serves the dummy Razorpay-lookalike payment UI inside an iframe."""
    return render_template("razorpay_dummy.html")


@app.route("/api/order/dummy-payment/confirm", methods=["POST"])
def dummy_payment_confirm():
    """Called from the dummy payment modal on success. Saves order + payment data."""
    if not is_logged_in():
        return jsonify(success=False, message="Login required")
    d = request.get_json()

    items      = d.get("items", [])
    address    = d.get("address", "")
    total      = float(d.get("total", 0))
    txn_id     = d.get("txn_id", "RZP" + str(uuid.uuid4())[:8].upper())
    method     = d.get("method", "Online")
    sub_method = d.get("sub_method", "")

    if not items or not address:
        return jsonify(success=False, message="Missing order data")

    # Place the order (reuse existing helper)
    oid = _place_order(
        items, address, total, "online",
        rz_oid=txn_id, rz_pid=txn_id
    )

    # Store detailed payment record for admin view
    payments_col.insert_one({
        "payment_id":   str(uuid.uuid4()),
        "order_id":     oid,
        "user_id":      session.get("user_id"),
        "user_name":    session.get("user_name"),
        "user_email":   session.get("user_email"),
        "txn_id":       txn_id,
        "amount":       total,
        "method":       method,
        "sub_method":   sub_method,
        "status":       "success",
        "created_at":   datetime.datetime.utcnow(),
    })

    print(f"[PAYMENT] TXN={txn_id} user={session.get('user_email')} amount=₹{total} method={method}")
    return jsonify(success=True, order_id=oid, txn_id=txn_id)


# ─── GIFT ORDER API ──────────────────────────────────────────
@app.route("/api/order/gift", methods=["POST"])
def gift_order():
    """Places a custom gift order (COD or Online) with gift metadata."""
    if not is_logged_in():
        return jsonify(success=False, message="Please login first")
    d = request.get_json()
    items    = d.get("items", [])
    address  = d.get("address", "").strip()
    total    = float(d.get("total", 0))
    method   = d.get("method", "online")   # 'cod' or 'online'
    txn_id   = d.get("txn_id", "")
    gift_meta = {
        "is_custom_gift":  True,
        "gift_occasion":   d.get("occasion", ""),
        "gift_recipient":  d.get("recipient", ""),
        "gift_message":    d.get("message", ""),
        "gift_pick_mode":  d.get("pick_mode", "single"),
        "gift_discount":   d.get("discount_pct", 0),
        "gift_code":       d.get("discount_code", ""),
        "gift_delivery":   d.get("delivery_date", ""),
    }
    if not items:   return jsonify(success=False, message="No items in gift order")
    if not address: return jsonify(success=False, message="Please enter delivery address")

    oid = str(uuid.uuid4())
    now = datetime.datetime.utcnow()

    # Parse custom delivery date if provided, else default 8 days
    if gift_meta["gift_delivery"]:
        try:
            eta = datetime.datetime.strptime(gift_meta["gift_delivery"], "%Y-%m-%d")
        except Exception:
            eta = now + datetime.timedelta(days=8)
    else:
        eta = now + datetime.timedelta(days=8)

    orders_col.insert_one({
        "order_id":          oid,
        "user_id":           session["user_id"],
        "user_name":         session["user_name"],
        "user_email":        session["user_email"],
        "items":             items,
        "total_amount":      total,
        "payment_method":    method,
        "order_status":      "processing",
        "payment_status":    "Paid" if method == "online" else "Pending (COD)",
        "delivery_address":  address,
        "booked_at":         now,
        "estimated_arrival": eta,
        **gift_meta,
    })

    for item in items:
        products_col.update_one(
            {"product_id": item["product_id"]},
            {"$inc": {"stock_quantity": -item["quantity"]}}
        )

    if method == "online" and txn_id:
        payments_col.insert_one({
            "payment_id": str(uuid.uuid4()),
            "order_id":   oid,
            "user_id":    session.get("user_id"),
            "user_name":  session.get("user_name"),
            "user_email": session.get("user_email"),
            "txn_id":     txn_id,
            "amount":     total,
            "method":     "Online",
            "sub_method": "Gift Order",
            "status":     "success",
            "created_at": now,
        })

    # Confirmation email
    # ── Occasion-personalised opening lines ──────────────────────────────────
    occ_lines = {
        "Birthday":        f"What a wonderful way to celebrate {gift_meta['gift_recipient']}'s big day! 🎂 Their smile is about to get even bigger.",
        "Wedding":         f"A beautiful union deserves the most beautiful chocolates. Wishing {gift_meta['gift_recipient']} a lifetime of sweetness! 💍",
        "Anniversary":     f"Here's to another year of love and indulgence! {gift_meta['gift_recipient']} is going to absolutely love this. 💑",
        "Baby Shower":     f"The sweetest little one deserves the sweetest welcome! {gift_meta['gift_recipient']} will treasure this gift. 👶",
        "Diwali":          f"May this Diwali gift light up {gift_meta['gift_recipient']}'s heart as brightly as the festival itself! 🪔",
        "Valentine's Day": f"Because some feelings are best expressed in rich, indulgent chocolate. {gift_meta['gift_recipient']} is one lucky person! ❤️",
        "Graduation":      f"All that hard work, and now the sweetest reward! {gift_meta['gift_recipient']} absolutely deserves this. 🎓",
        "Just Because":    f"The best gifts need no reason — and {gift_meta['gift_recipient']} is about to find out why! 🎁",
    }
    occ_msg = occ_lines.get(gift_meta["gift_occasion"],
        f"A thoughtful gift for {gift_meta['gift_recipient']} — crafted with care and wrapped with love. 🍫")

    mix_note = (
        f"<p style='color:#b0906a;font-size:13px;margin:0 0 16px;font-style:italic'>"
        f"✨ This is an AI-curated Special Mix — our recommendation engine handpicked these flavours "
        f"especially for a {gift_meta['gift_occasion']} occasion.</p>"
    ) if gift_meta["gift_pick_mode"] == "special" else ""

    msg_block = (
        f"<div style='background:#2a1200;border-left:3px solid #d4820a;border-radius:0 8px 8px 0;"
        f"padding:12px 16px;margin:0 0 18px'>"
        f"<p style='color:#a07840;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin:0 0 4px'>Gift Message</p>"
        f"<p style='color:#f5c842;font-size:14px;font-style:italic;margin:0'>&ldquo;{gift_meta['gift_message']}&rdquo;</p>"
        f"</div>"
    ) if gift_meta.get("gift_message") else ""

    items_rows = "".join(
        f"<tr style='border-bottom:1px solid #d4820a22'>"
        f"<td style='padding:10px 12px;color:#e8d5b0;font-size:14px'>{i['name']}</td>"
        f"<td style='padding:10px 12px;color:#e8d5b0;font-size:14px;text-align:center'>{i['quantity']}</td>"
        f"<td style='padding:10px 12px;color:#f5c842;font-size:14px;text-align:right;font-weight:bold'>&#8377;{i['price']}</td>"
        f"</tr>"
        for i in items
    )

    orig_total   = sum(float(i["price"]) * int(i["quantity"]) for i in items)
    amount_saved = round(orig_total - float(total))

    body = (
        # Opening personalised line
        f"<p style='color:#e8d5b0;font-size:16px;margin:0 0 6px'>"
        f"Hi <strong style='color:#f5c842'>{session['user_name']}</strong>,</p>"
        f"<p style='color:#e8d5b0;font-size:15px;line-height:1.7;margin:0 0 20px'>{occ_msg}</p>"

        # Occasion + recipient badge row
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px'>"
        f"<span style='background:#3d1c00;border:1px solid #d4820a44;border-radius:20px;"
        f"padding:5px 14px;color:#d4820a;font-size:13px;font-weight:700'>"
        f"🎉 {gift_meta['gift_occasion']}</span>"
        f"<span style='background:#3d1c00;border:1px solid #d4820a44;border-radius:20px;"
        f"padding:5px 14px;color:#f5c842;font-size:13px'>"
        f"🎁 For: {gift_meta['gift_recipient']}</span>"
        f"</div>"

        # Custom message card
        f"{msg_block}"

        # Mix note if AI special
        f"{mix_note}"

        # Items table
        f"<table style='width:100%;border-collapse:collapse;background:#2a1200;"
        f"border:1px solid #d4820a33;border-radius:8px;overflow:hidden;margin-bottom:16px'>"
        f"<tr style='background:#3d1c00'>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:12px;text-align:left;text-transform:uppercase;letter-spacing:0.5px'>Chocolate</th>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:12px;text-align:center;text-transform:uppercase;letter-spacing:0.5px'>Qty</th>"
        f"<th style='padding:10px 12px;color:#d4820a;font-size:12px;text-align:right;text-transform:uppercase;letter-spacing:0.5px'>Price</th>"
        f"</tr>{items_rows}</table>"

        # Pricing summary
        f"<div style='background:#2a1200;border:1px solid #d4820a33;border-radius:8px;padding:14px 16px;margin-bottom:16px'>"
        f"<div style='display:flex;justify-content:space-between;padding:4px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Original Price</span>"
        f"<span style='color:#888;font-size:13px;text-decoration:line-through'>&#8377;{round(orig_total)}</span>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;padding:4px 0'>"
        f"<span style='color:#a07840;font-size:13px'>{gift_meta['gift_discount']}% Discount Applied</span>"
        f"<span style='color:#6fcf97;font-size:13px;font-weight:700'>&#8722; &#8377;{amount_saved}</span>"
        f"</div>"
        f"<div style='border-top:1px solid #d4820a33;margin:8px 0 4px'></div>"
        f"<div style='display:flex;justify-content:space-between;padding:4px 0'>"
        f"<span style='color:#d4820a;font-size:15px;font-weight:700'>You Pay</span>"
        f"<span style='color:#f5c842;font-size:18px;font-weight:900'>&#8377;{round(total)}</span>"
        f"</div>"
        f"</div>"

        # Delivery
        f"<p style='color:#e8d5b0;font-size:14px;margin:0 0 6px'>"
        f"<strong style='color:#d4820a'>&#128666; Estimated Delivery:</strong> "
        f"<span style='color:#fff;font-weight:600'>{eta.strftime('%A, %d %b %Y')}</span></p>"

        # Order ID
        f"<p style='color:#a07840;font-size:12px;margin:10px 0 0'>"
        f"Order ID: <code style='color:#f5c842;font-size:12px;word-break:break-all'>{oid}</code></p>"

        # Closing
        f"<hr style='border:none;border-top:1px solid rgba(212,130,10,0.2);margin:20px 0'>"
        f"<p style='color:#a07840;font-size:13px;line-height:1.6;margin:0'>"
        f"Our team is already crafting this gift with extra care. 🍫<br>"
        f"<strong style='color:#d4820a'>The ChocoBite Team</strong></p>"
    )

    # Attractive subject line personalised to occasion
    occ_subjects = {
        "Birthday":        f"🎂 {gift_meta['gift_recipient']}'s Birthday Gift is Confirmed — ChocoBite",
        "Wedding":         f"💍 Wedding Gift for {gift_meta['gift_recipient']} — Order Confirmed",
        "Anniversary":     f"💑 Anniversary Chocolates for {gift_meta['gift_recipient']} — Confirmed!",
        "Baby Shower":     f"👶 Baby Shower Gift Confirmed — Sweet Arrival on the Way!",
        "Diwali":          f"🪔 Your Diwali Gift Box is Confirmed — ChocoBite",
        "Valentine's Day": f"❤️ Valentine's Gift for {gift_meta['gift_recipient']} — Order Confirmed",
        "Graduation":      f"🎓 Graduation Gift Confirmed — Well Done!",
        "Just Because":    f"🎁 Your Surprise Gift for {gift_meta['gift_recipient']} is Confirmed!",
    }
    subject = occ_subjects.get(gift_meta["gift_occasion"],
        f"🎁 Custom Gift Order Confirmed — ChocoBite")

    send_email(session["user_email"], subject,
               email_wrap("Your Gift Order is Confirmed! 🎁", body))

    return jsonify(success=True, order_id=oid, message="Gift order placed successfully!")



# ─── CUSTOM BAR ORDER API ─────────────────────────────────────
@app.route("/api/order/custom-bar", methods=["POST"])
def custom_bar_order():
    """Places a custom bar design order with full design metadata."""
    if not is_logged_in():
        return jsonify(success=False, message="Please login first")
    d       = request.get_json()
    items   = d.get("items", [])
    address = d.get("address", "").strip()
    total   = float(d.get("total", 0))
    method  = d.get("method", "online")
    txn_id  = d.get("txn_id", "")
    meta = {
        "is_custom_design": True,
        "design_bar_name":  d.get("bar_name", ""),
        "design_message":   d.get("bar_message", ""),
        "design_wrapper":   d.get("wrapper_colour", ""),
        "design_pattern":   d.get("pattern", ""),
        "design_font":      d.get("font_style", ""),
        "design_sugar_pref":d.get("sugar_pref", ""),
        "design_discount":  d.get("discount_pct", 0),
        "design_code":      d.get("discount_code", ""),
        "design_delivery":  d.get("delivery_date", ""),
    }
    if not items:   return jsonify(success=False, message="No items in order")
    if not address: return jsonify(success=False, message="Please enter delivery address")

    oid = str(uuid.uuid4())
    now = datetime.datetime.utcnow()
    if meta["design_delivery"]:
        try:    eta = datetime.datetime.strptime(meta["design_delivery"], "%Y-%m-%d")
        except: eta = now + datetime.timedelta(days=8)
    else:
        eta = now + datetime.timedelta(days=8)

    orders_col.insert_one({
        "order_id":          oid,
        "user_id":           session["user_id"],
        "user_name":         session["user_name"],
        "user_email":        session["user_email"],
        "items":             items,
        "total_amount":      total,
        "payment_method":    method,
        "order_status":      "processing",
        "payment_status":    "Paid" if method == "online" else "Pending (COD)",
        "delivery_address":  address,
        "booked_at":         now,
        "estimated_arrival": eta,
        **meta,
    })
    for item in items:
        products_col.update_one({"product_id": item["product_id"]},
                                {"$inc": {"stock_quantity": -item["quantity"]}})
        # If this item used a launch offer, increment buyer count
        if item.get("used_launch_offer"):
            now_ts = datetime.datetime.utcnow()
            p = products_col.find_one({"product_id": item["product_id"]})
            if p:
                lo = p.get("launch_offer", {})
                new_count = lo.get("buyers_count", 0) + item.get("quantity", 1)
                updates = {"launch_offer.buyers_count": new_count}
                # Auto-deactivate if max buyers reached or expired
                if new_count >= lo.get("max_buyers", 10) or                    (lo.get("expires_at") and lo["expires_at"] < now_ts):
                    updates["launch_offer.active"] = False
                products_col.update_one(
                    {"product_id": item["product_id"]},
                    {"$set": updates}
                )

    if method == "online" and txn_id:
        payments_col.insert_one({
            "payment_id": str(uuid.uuid4()),
            "order_id":   oid,
            "user_id":    session.get("user_id"),
            "user_name":  session.get("user_name"),
            "user_email": session.get("user_email"),
            "txn_id":     txn_id,
            "amount":     total,
            "method":     "Online",
            "sub_method": "Custom Bar Design",
            "status":     "success",
            "created_at": now,
        })

    # ── Confirmation email ────────────────────────────────────────────────────
    qty         = sum(int(i.get("quantity", 1)) for i in items)
    bar_name    = items[0]["name"] if items else "Custom Bar"
    custom_fee  = qty * 50
    orig_total  = total / (1 - float(meta["design_discount"] or 0) / 100) if meta["design_discount"] else total
    amount_saved = round(orig_total - total)

    design_details = ""
    if meta["design_bar_name"]:
        design_details += f"<div style='display:flex;justify-content:space-between;padding:4px 0'><span style='color:#a07840;font-size:13px'>Text on bar</span><span style='color:#f5c842;font-size:13px;font-style:italic'>&ldquo;{meta['design_bar_name']}&rdquo;</span></div>"
    if meta["design_message"]:
        design_details += f"<div style='display:flex;justify-content:space-between;padding:4px 0'><span style='color:#a07840;font-size:13px'>Inner message</span><span style='color:#e8d5b0;font-size:13px;font-style:italic'>&ldquo;{meta['design_message']}&rdquo;</span></div>"
    if meta["design_wrapper"]:
        design_details += f"<div style='display:flex;justify-content:space-between;padding:4px 0'><span style='color:#a07840;font-size:13px'>Wrapper</span><span style='color:#e8d5b0;font-size:13px'>{meta['design_wrapper']}</span></div>"
    if meta["design_pattern"] and meta["design_pattern"] != "None":
        design_details += f"<div style='display:flex;justify-content:space-between;padding:4px 0'><span style='color:#a07840;font-size:13px'>Pattern</span><span style='color:#e8d5b0;font-size:13px'>{meta['design_pattern']}</span></div>"
    if meta["design_sugar_pref"]:
        design_details += f"<div style='display:flex;justify-content:space-between;padding:4px 0'><span style='color:#a07840;font-size:13px'>Preference</span><span style='color:#e8d5b0;font-size:13px'>{'Sugar Free &#127807;' if meta['design_sugar_pref']=='sugarfree' else 'With Sugar &#127851;'}</span></div>"

    email_body = (
        f"<p style='color:#e8d5b0;font-size:15px;margin:0 0 6px'>"
        f"Hi <strong style='color:#f5c842'>{session['user_name']}</strong>,</p>"
        f"<p style='color:#e8d5b0;font-size:15px;line-height:1.7;margin:0 0 18px'>"
        f"Your custom designed chocolate bar order has been confirmed! &#127912; "
        f"Our chocolatiers are already getting to work on your unique creation.</p>"

        # Product + design details
        f"<div style='background:#2a1200;border:1px solid #d4820a33;border-radius:10px;"
        f"padding:16px 18px;margin-bottom:16px'>"
        f"<p style='color:#d4820a;font-size:12px;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:1px;margin:0 0 10px'>&#10022; Your Custom Bar Design</p>"
        f"<div style='display:flex;justify-content:space-between;padding:4px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Base bar</span>"
        f"<span style='color:#f5c842;font-size:13px;font-weight:700'>{bar_name.replace(' (Custom Bar)','')}</span></div>"
        f"<div style='display:flex;justify-content:space-between;padding:4px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Quantity</span>"
        f"<span style='color:#e8d5b0;font-size:13px'>{qty} bar{'s' if qty>1 else ''}</span></div>"
        f"{design_details}"
        f"</div>"

        # Pricing
        f"<div style='background:#2a1200;border:1px solid #d4820a22;border-radius:8px;"
        f"padding:14px 16px;margin-bottom:16px'>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Product total</span>"
        f"<span style='color:#e8d5b0;font-size:13px'>&#8377;{round(orig_total - custom_fee)}</span></div>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Customisation ({qty} &#215; &#8377;50)</span>"
        f"<span style='color:#e8d5b0;font-size:13px'>&#8377;{custom_fee}</span></div>"
        + (f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
           f"<span style='color:#a07840;font-size:13px'>{meta['design_discount']}% Discount</span>"
           f"<span style='color:#6fcf97;font-size:13px;font-weight:700'>&#8722; &#8377;{amount_saved}</span></div>"
           if meta["design_discount"] else "") +
        f"<div style='border-top:1px solid #d4820a33;margin:8px 0 4px'></div>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#d4820a;font-size:15px;font-weight:700'>You Pay</span>"
        f"<span style='color:#f5c842;font-size:18px;font-weight:900'>&#8377;{round(total)}</span></div>"
        f"</div>"

        f"<p style='color:#e8d5b0;font-size:14px;margin:0 0 6px'>"
        f"<strong style='color:#d4820a'>&#128666; Estimated Delivery:</strong> "
        f"<span style='color:#fff;font-weight:600'>{eta.strftime('%A, %d %b %Y')}</span></p>"
        f"<p style='color:#a07840;font-size:12px;margin:10px 0 0'>"
        f"Order ID: <code style='color:#f5c842;font-size:12px'>{oid}</code></p>"
        f"<hr style='border:none;border-top:1px solid rgba(212,130,10,0.2);margin:20px 0'>"
        f"<p style='color:#a07840;font-size:13px;line-height:1.6;margin:0'>"
        f"Your design will be verified by our team before production begins. "
        f"Sit back and let us craft your perfect bar! &#127851;<br>"
        f"<strong style='color:#d4820a'>The ChocoBite Team</strong></p>"
    )

    send_email(
        session["user_email"],
        f"&#127912; Your Custom Bar Design is Confirmed — ChocoBite",
        email_wrap("Custom Bar Order Confirmed! &#127912;", email_body)
    )

    return jsonify(success=True, order_id=oid, message="Custom bar order placed!")



# ─── SEASONAL OFFERS API (ML-powered) ───────────────────────────────────────
# Cache: {season_name: {"offers": [...], "generated_at": datetime}}
_seasonal_cache = {}

@app.route("/api/seasonal-offers")
def seasonal_offers():
    """
    Uses seasonal_recommender.py (sklearn KMeans) to:
    1. Read all products and non-cancelled orders from DB
    2. Cluster products by seasonal purchase frequency
    3. Return 7 offers for the current season
    Offers are cached per season and refreshed when season changes or on server restart.
    As more users buy products → re-running refreshes the ML model automatically.
    """
    import datetime as dt

    # Determine current season
    m = dt.datetime.utcnow().month
    season_name = ("Summer"  if 3  <= m <= 5  else
                   "Monsoon" if 6  <= m <= 9  else
                   "Autumn"  if 10 <= m <= 11 else "Winter")

    # Serve from cache if same season
    cached = _seasonal_cache.get(season_name)
    if cached:
        return jsonify(cached["data"])

    # Pull data from DB
    products = list(products_col.find({}, {"_id": 0}))
    orders   = list(orders_col.find(
        {"order_status": {"$nin": ["cancelled"]}},
        {"items": 1, "booked_at": 1}
    ).max_time_ms(2000).limit(500))  # cap at 500 orders, 2s max

    if ML_AVAILABLE:
        result = _ml_seasonal(products, orders, n_offers=7)
    else:
        # Fallback: simple frequency sort if sklearn not installed
        from collections import Counter
        season_months = {"Summer":[3,4,5],"Monsoon":[6,7,8,9],"Autumn":[10,11],"Winter":[12,1,2]}
        months        = season_months.get(season_name, [])
        freq          = Counter()
        for o in orders:
            bk = o.get("booked_at")
            om = bk.month if bk and hasattr(bk,"month") else m
            if om in months:
                for i in o.get("items", []):
                    freq[i.get("product_id","")] += i.get("quantity",1)
        products_sorted = sorted(products, key=lambda p: freq.get(p.get("product_id",""),0), reverse=True)
        emoji = {"Summer":"☀️","Monsoon":"🌧️","Autumn":"🍂","Winter":"❄️"}.get(season_name,"🌿")
        offers = []
        for idx, p in enumerate(products_sorted[:7]):
            disc  = 14 + (idx % 11)
            orig  = float(p.get("price",299))
            offers.append({
                "product_id":  p["product_id"],
                "name":        p.get("name",""),
                "tagline":     p.get("tagline") or p.get("description","")[:65],
                "image_url":   p.get("image_url",""),
                "price":       orig,
                "final_price": round(orig*(1-disc/100)),
                "discount":    disc,
                "code":        season_name[:3].upper()+str(disc),
                "similar":     [],
            })
        result = {"season": season_name, "emoji": emoji, "offers": offers}

    _seasonal_cache[season_name] = {
        "data":         result,
        "generated_at": dt.datetime.utcnow(),
    }
    return jsonify(result)

@app.route("/api/seasonal-offers/refresh", methods=["POST"])
def refresh_seasonal_offers():
    """Force-refresh the seasonal ML cache (e.g. after new orders come in)."""
    _seasonal_cache.clear()
    return jsonify(success=True, message="Cache cleared — next request will rerun ML model")


# ─── FEEDBACK API ────────────────────────────────────────────

# Weighted-average rating helper
RATING_WEIGHT = 20  # W: once N reaches 20, community opinion equals seed weight

def compute_weighted_rating(product_id):
    """
    Weighted Bayesian average:
        rating = (R_user * N + R_base * W) / (N + W)
    R_user = mean of all user ratings for this product
    N      = total number of user ratings
    R_base = original admin/seed rating (preserved as base_rating)
    W      = 20
    """
    product = products_col.find_one({"product_id": product_id},
                                     {"rating": 1, "base_rating": 1, "_id": 0})
    if not product:
        return None

    # Preserve original rating as base_rating on first review
    r_base = product.get("base_rating")
    if r_base is None:
        r_base = float(product.get("rating", 4.0))
        products_col.update_one({"product_id": product_id},
                                {"$set": {"base_rating": r_base}})

    agg = list(product_reviews_col.aggregate([
        {"$match": {"product_id": product_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}}
    ]))

    if not agg:
        return round(r_base, 1)

    r_user = float(agg[0]["avg"])
    n      = int(agg[0]["count"])
    w      = RATING_WEIGHT

    weighted = (r_user * n + r_base * w) / (n + w)
    return round(weighted, 1)


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """General site feedback (no product) -- stored in 'feedback' collection."""
    d       = request.get_json()
    comment = (d.get("comment") or d.get("message") or "").strip()
    user_id = session.get("user_id", "anonymous")

    if not comment:
        return jsonify(success=False, message="Please enter a comment")

    feedback_col.insert_one({
        "feedback_id": str(uuid.uuid4()),
        "user_id":     user_id,
        "name":        d.get("name", ""),
        "email":       d.get("email", ""),
        "rating":      max(1, min(5, int(d.get("rating", 5)))),
        "comment":     comment,
        "created_at":  datetime.datetime.utcnow()
    })
    return jsonify(success=True, message="Thank you for your feedback!")


@app.route("/api/product-review", methods=["POST"])
def submit_product_review():
    """Product-specific review -- stored in 'product_reviews' collection.
    Updates product rating using weighted Bayesian average.
    """
    if not is_logged_in():
        return jsonify(success=False, message="Please log in to submit a review")

    d          = request.get_json()
    comment    = (d.get("comment") or "").strip()
    product_id = d.get("product_id", "").strip()
    rating     = max(1, min(5, int(d.get("rating", 5))))
    user_id    = session["user_id"]
    user_name  = session.get("user_name", "") or d.get("name", "").strip()

    if not comment:
        return jsonify(success=False, message="Please write your review")
    if not product_id:
        return jsonify(success=False, message="Invalid product")

    # One review per user per product
    if product_reviews_col.find_one({"user_id": user_id, "product_id": product_id}):
        return jsonify(success=False, message="You have already reviewed this product")

    # Fetch product name for display in admin
    prod_doc     = products_col.find_one({"product_id": product_id}, {"name": 1, "_id": 0})
    product_name = prod_doc.get("name", "") if prod_doc else ""

    product_reviews_col.insert_one({
        "review_id":    str(uuid.uuid4()),
        "user_id":      user_id,
        "user_name":    user_name,
        "product_id":   product_id,
        "product_name": product_name,
        "rating":       rating,
        "comment":      comment,
        "status":       "pending",
        "created_at":   datetime.datetime.utcnow()
    })

    # Recompute product rating with weighted average
    new_rating = compute_weighted_rating(product_id)
    if new_rating is not None:
        products_col.update_one(
            {"product_id": product_id},
            {"$set": {"rating": new_rating}}
        )

    return jsonify(success=True, message="Thank you for your review!", new_rating=new_rating)


@app.route("/api/user/mark-reply-seen", methods=["POST"])
def mark_reply_seen():
    """Mark a product review reply as seen by the user.
    Called when user clicks 'View product' from the feedback page.
    """
    if not is_logged_in():
        return jsonify(success=False)
    d         = request.get_json() or {}
    review_id = d.get("review_id", "")
    user_id   = session["user_id"]
    if not review_id:
        return jsonify(success=False, message="Missing review_id")
    product_reviews_col.update_one(
        {"review_id": review_id, "user_id": user_id},
        {"$set": {"reply_seen": True, "reply_seen_at": datetime.datetime.utcnow()}}
    )
    return jsonify(success=True)


@app.route("/api/user/my-review-replies")
def my_review_replies():
    """Returns product reviews by the logged-in user that have admin replies."""
    if not is_logged_in():
        return jsonify([])
    user_id = session["user_id"]
    reviews = list(
        product_reviews_col.find(
            {"user_id": user_id,
             "admin_reply": {"$exists": True, "$ne": ""},
             "reply_seen": {"$ne": True}},
            {"_id": 0}
        ).sort("replied_at", -1)
    )
    for r in reviews:
        if "created_at" in r and hasattr(r["created_at"], "strftime"):
            r["created_at"] = r["created_at"].strftime("%d %b %Y")
        if "replied_at" in r and hasattr(r["replied_at"], "strftime"):
            r["replied_at"] = r["replied_at"].strftime("%d %b %Y")
    return jsonify(reviews)


@app.route("/api/product-review/list")
def product_review_list():
    """Return all reviews for a specific product from product_reviews collection."""
    pid = request.args.get("product_id", "")
    if not pid:
        return jsonify([])
    items = list(
        product_reviews_col.find({"product_id": pid}, {"_id": 0})
        .sort("created_at", -1)
        .limit(100)
    )
    for r in items:
        if "created_at" in r and hasattr(r["created_at"], "strftime"):
            r["created_at"] = r["created_at"].strftime("%d %b %Y")
    return jsonify(items)


@app.route("/api/feedback/list")
def feedback_list():
    """General site feedback list (for feedback.html page only)."""
    items = list(feedback_col.find({}, {"_id": 0}).sort("created_at", -1).limit(20))
    for f in items:
        if "created_at" in f and hasattr(f["created_at"], "strftime"):
            f["created_at"] = f["created_at"].strftime("%d %b %Y")
    return jsonify(items)



# ─── CONTACT API ─────────────────────────────────────────────

@app.route("/api/contact", methods=["POST"])
def contact_submit():
    # Only registered/logged-in users can send contact messages
    if not is_logged_in():
        return jsonify(success=False, message="Please log in to send a message.")

    d       = request.get_json()
    name    = d.get("name",    "").strip()
    email   = d.get("email",   "").strip()
    subject = d.get("subject", "").strip()
    message = d.get("message", "").strip()

    if not message:
        return jsonify(success=False, message="Please enter a message.")

    # Save to DB
    contacts_col.insert_one({
        "name":       name,
        "email":      email,
        "subject":    subject,
        "message":    message,
        "user_id":    session.get("user_id", ""),
        "created_at": datetime.datetime.utcnow()
    })

    # Send email notification to admin
    body = (
        f"<p><b style='color:#d4820a'>From:</b> {name} ({email})</p>"
        f"<p><b style='color:#d4820a'>Subject:</b> {subject}</p>"
        f"<hr style='border-color:rgba(212,130,10,0.2);margin:14px 0'>"
        f"<p style='line-height:1.7'>{message}</p>"
    )
    try:
        send_email(
            EMAIL_USER,
            f"ChocoBite Contact: {subject}",
            email_wrap(f"New Message from {name}", body)
        )
    except Exception:
        pass  # don't block user if email fails

    return jsonify(success=True, message="Message sent! We'll get back to you soon. 🍫")





# ============================================================
#  RESEED CAT-1 — visit http://localhost:5000/reseed-cat1
#  Deletes ALL old category-1 products (GloryBean chips etc.)
#  and inserts the 11 correct Cocoa Beans & Chips products.
#  Does NOT touch category 2 or 3.
# ============================================================
@app.route("/reseed-cat1")
def reseed_cat1():
    # Remove all old category-1 products
    products_col.delete_many({"category_id": 1})

    # Update category name
    categories_col.update_one(
        {"category_id": 1},
        {"$set": {"category_name": "Cocoa Beans & Chips", "slug": "seeds"}}
    )
    # If category doesn't exist yet, insert it
    if not categories_col.find_one({"category_id": 1}):
        categories_col.insert_one({
            "category_id": 1,
            "category_name": "Cocoa Beans & Chips",
            "slug": "seeds",
            "description": "Premium cocoa beans and artisan chips"
        })

    now = datetime.datetime.utcnow()
    i1  = "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500"
    i2  = "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500"
    i3  = "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500"
    i4  = "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500"

    def p(name, desc, price, img, stock, rating, weight,
          mrp, tagline, why_this, health_benefits, pack_type, price_per_100g):
        return {
            "product_id":      str(uuid.uuid4()),
            "category_id":     1,
            "name":            name,
            "description":     desc,
            "price":           float(price),
            "mrp":             float(mrp),
            "tagline":         tagline,
            "why_this":        why_this,
            "health_benefits": health_benefits,
            "pack_type":       pack_type,
            "price_per_100g":  price_per_100g,
            "image_url":       img,
            "is_sugarless":    True,
            "stock_quantity":  stock,
            "rating":          float(rating),
            "weight":          weight,
            "created_at":      now,
        }

    _ch = ("A cup of your Criollo is more than a luxury — it's a ritual for your heart. "
           "With 40x the antioxidants of blueberries and a natural dose of the bliss molecule, "
           "it's the only indulgence that loves you back.")

    _fh = ("The untamed power of the Amazon fuels your body with raw, robust energy of the "
           "Forastero bean. Known as the guardian of cocoa, this variety is a concentrated source "
           "of metabolic minerals and plant-based iron, designed to support physical stamina and "
           "bone strength. Its deep, intense profile is packed with potassium for muscle recovery "
           "and antioxidants that fight daily fatigue.")

    _chips_h = ("Pure cocoa power in every drop — packed with antioxidants and flavonoids that "
                "support heart health and mental clarity.")

    new_products = [
        # ── Royal Criollo Cocoa ─────────────────────────────────────────
        p("The Heirloom Batch",
          "A first encounter with the ancient bean. Royal Criollo cocoa — the rarest cacao on "
          "earth, prized for its delicate floral complexity and smooth finish.",
          499, i1, 40, 4.8, "150g", 780,
          "A first encounter with the ancient bean",
          "Crafted for the modern alchemist, this 150g batch is the perfect size for your private "
          "kitchen rituals. Enough to share, but crafted for you to keep.",
          _ch, "Small", "₹499 / 100g"),

        p("The Royal Tribute",
          "The sacred drink of emperors, preserved for you. Royal Criollo cocoa at its most "
          "refined — our golden ratio pack for dedicated enthusiasts.",
          1899, i2, 25, 4.9, "450g", 1900,
          "The sacred drink of emperors, preserved for you",
          "This is our golden ratio pack — the ideal volume for their lifestyle. "
          "Designed for the dedicated enthusiast.",
          _ch, "Premium", "₹422 / 100g"),

        p("The Sun Stone Collection",
          "Reviving the ritual of the ancient feast. A full kilogram of Royal Criollo cocoa "
          "for large gatherings — the luxury of sharing the world's finest bean.",
          3499, i4, 15, 4.7, "1000g", 3600,
          "Reviving the ritual of the ancient feast",
          "A full kilogram for a large gathering (25+ people) to experience the luxury. "
          "This bulk pack is crafted for those who believe the finest things in life "
          "are meant to be enjoyed together.",
          _ch, "Party", "₹349 / 100g"),

        # ── Grand Forastero Cocoa ───────────────────────────────────────
        p("The Amazon Origin",
          "The raw spirit of the rainforest. Forastero originated in the Amazon basin — "
          "wild, untamed, and robustly chocolatey.",
          449, i1, 50, 4.5, "150g", 460,
          "The raw spirit of the rainforest",
          "Forastero originated in the Amazon basin. This name highlights its wild, untamed roots.",
          _fh, "Small", "₹299 / 100g"),

        p("The Earth's Harvest",
          "Bold, deep, and timelessly chocolate. Forastero is famous for its classic, strong "
          "chocolatey flavour profile — reliable and naturally strong.",
          999, i2, 30, 4.6, "450g", 1010,
          "Bold, deep, and timelessly chocolate",
          "Forastero is famous for its classic, strong chocolatey flavour profile. "
          "This name suggests reliability and natural strength.",
          _fh, "Premium", "₹222 / 100g"),

        p("The Foundation Batch",
          "The soul of the world's cocoa ritual. Since most of the world's chocolate is made "
          "from Forastero, this batch honours its role as the essential base.",
          1849, i4, 18, 4.4, "1000g", 1900,
          "The soul of the world's cocoa ritual",
          "Since most of the world's chocolate is made from Forastero, this name honours "
          "its role as the essential base for all chocolate lovers.",
          _fh, "Party", "₹184 / 100g"),

        # ── Cocoa Chips — The Sacred Gems ──────────────────────────────
        p("Obsidian Droplets",
          "The fundamental spark of every creation. High-stability cocoa chips that hold "
          "their peak flavour under high heat — a baker's essential.",
          599, i3, 55, 4.7, "250g", 599,
          "The fundamental spark of every creation",
          "These are high-stability chips that hold their peak flavour under high heat. "
          "Perfect for the purist baker who wants a consistent, deep cocoa melt in every bite.",
          _chips_h, "Premium", "₹239 / 100g"),

        p("Lunar Orbs",
          "Perfectly balanced, infinitely smooth. Spherical cocoa chips for an even, "
          "melt-in-the-mouth experience. Ideal for professional garnishing.",
          649, i1, 45, 4.6, "250g", 649,
          "Perfectly balanced, infinitely smooth",
          "The spherical shape allows for a more even melt-in-the-mouth experience. "
          "Ideal for professional garnishing or panning (coating nuts), giving your "
          "desserts a polished, high-end look.",
          _chips_h, "Premium", "₹259 / 100g"),

        p("Ixchel's Devotion",
          "The language of the heart, etched in cocoa. Heart-shaped premium cocoa chips "
          "for anniversary baking, Valentine's gifts and luxury toppings.",
          699, i2, 40, 4.8, "250g", 699,
          "The language of the heart, etched in cocoa",
          "These are your emotional premium product. Perfect for anniversary baking, "
          "Valentine's Day gifts, or luxury topping for a loved one's morning bowl. "
          "They turn a simple brownie into a romantic gesture.",
          _chips_h, "Premium", "₹279 / 100g"),

        p("Celestial Spark",
          "A taste of the heavens in every morsel. Star-shaped cocoa chips with sharp edges "
          "for unique snap and texture — the best choice for festive decorating.",
          699, i3, 38, 4.7, "250g", 699,
          "A taste of the heavens in every morsel",
          "The sharp edges of the star shape provide a unique snap and texture. "
          "They are the best choice for decorating festive cakes or topping smoothie bowls "
          "where visual wow-factor is the priority.",
          _chips_h, "Premium", "₹279 / 100g"),

        p("The Cosmos Medley",
          "The complete map of ancient chocolate artistry. All four cocoa chip shapes in one "
          "500g pack — the ultimate creative baker's toolkit.",
          1299, i4, 30, 4.9, "500g", 1299,
          "The complete map of ancient chocolate artistry",
          "This is your all-in-one solution. It offers the best value and variety for "
          "creative bakers who want to experiment with different textures and shapes in a "
          "single recipe. It saves the customer from buying four separate packs.",
          _chips_h, "Premium", "₹259 / 100g"),
    ]

    products_col.insert_many(new_products)

    cat1_count = products_col.count_documents({"category_id": 1})
    return f"""
    <html><body style="font-family:monospace;background:#111;color:#6fcf97;padding:40px">
    <h2>✅ Category 1 re-seeded!</h2>
    <p>Old products removed. New products inserted: <b>{len(new_products)}</b></p>
    <p>Current Cat-1 total in DB: <b>{cat1_count}</b></p>
    <br>
    <p style="color:#f5c842">Products now in Cocoa Beans &amp; Chips:</p>
    <ol style="color:#e8d5b0">
      <li>The Heirloom Batch (Royal Criollo – Small 150g) — ₹499</li>
      <li>The Royal Tribute (Royal Criollo – Premium 450g) — ₹1,899</li>
      <li>The Sun Stone Collection (Royal Criollo – Party 1kg) — ₹3,499</li>
      <li>The Amazon Origin (Grand Forastero – Small 150g) — ₹449</li>
      <li>The Earth's Harvest (Grand Forastero – Premium 450g) — ₹999</li>
      <li>The Foundation Batch (Grand Forastero – Party 1kg) — ₹1,849</li>
      <li>Obsidian Droplets (Classic Chips 250g) — ₹599</li>
      <li>Lunar Orbs (Round Chips 250g) — ₹649</li>
      <li>Ixchel's Devotion (Heart Chips 250g) — ₹699</li>
      <li>Celestial Spark (Star Chips 250g) — ₹699</li>
      <li>The Cosmos Medley (Mixed 500g) — ₹1,299</li>
    </ol>
    <br>
    <a href="/products?cat=seeds" style="color:#d4820a;font-size:18px">→ View Products Page</a>
    </body></html>"""


@app.route("/fix-seeds-sugarless")
def fix_seeds_sugarless():
    """
    One-time migration: marks all existing Choco Beans & Chips (category_id=1)
    products as is_sugarless=True.
    Visit: http://localhost:5000/fix-seeds-sugarless
    """
    result = products_col.update_many(
        {"category_id": 1},
        {"$set": {"is_sugarless": True}}
    )
    return f"""
    <html><body style="font-family:monospace;background:#111;color:#6fcf97;padding:40px">
    <h2>✅ Migration complete!</h2>
    <p>Choco Beans &amp; Chips products updated: <b>{result.modified_count}</b></p>
    <p>All category 1 products now have is_sugarless = True</p>
    <br><a href="/products" style="color:#f5c842">→ Go to Products page</a>
    </body></html>"""


@app.route("/customize")
def customize_page():
    return render_template("customize.html")

# ─── ORDERS PAGE ─────────────────────────────────────────────────────────────

@app.route("/orders")
def orders_page():
    return render_template("orders.html")


@app.route("/api/orders/active")
def orders_active():
    if not is_logged_in():
        return jsonify(success=False, orders=[])
    now = datetime.datetime.utcnow()
    # Auto-mark past orders as delivered
    orders_col.update_many(
        {"user_id": session["user_id"], "order_status": "processing",
         "estimated_arrival": {"$lt": now}},
        {"$set": {"order_status": "delivered"}}
    )
    orders = list(orders_col.find(
        {"user_id": session["user_id"], "order_status": {"$nin": ["delivered","cancelled"]}},
        {"_id": 0}
    ).sort("booked_at", -1))
    for o in orders:
        if isinstance(o.get("booked_at"), datetime.datetime):
            o["booked_at"] = o["booked_at"].isoformat()
        if isinstance(o.get("estimated_arrival"), datetime.datetime):
            o["estimated_arrival"] = o["estimated_arrival"].isoformat()
    return jsonify(success=True, orders=orders)


@app.route("/api/orders/history")
def orders_history():
    if not is_logged_in():
        return jsonify(success=False, orders=[])
    now = datetime.datetime.utcnow()
    orders_col.update_many(
        {"user_id": session["user_id"], "order_status": "processing",
         "estimated_arrival": {"$lt": now}},
        {"$set": {"order_status": "delivered"}}
    )
    orders = list(orders_col.find(
        {"user_id": session["user_id"], "order_status": {"$in": ["delivered","cancelled"]}},
        {"_id": 0}
    ).sort("booked_at", -1))
    for o in orders:
        if isinstance(o.get("booked_at"), datetime.datetime):
            o["booked_at"] = o["booked_at"].isoformat()
        if isinstance(o.get("estimated_arrival"), datetime.datetime):
            o["estimated_arrival"] = o["estimated_arrival"].isoformat()
    return jsonify(success=True, orders=orders)


@app.route("/api/order/cancel", methods=["POST"])
def cancel_order():
    if not is_logged_in():
        return jsonify(success=False, message="Please login first")
    order_id = request.get_json().get("order_id","").strip()
    order    = orders_col.find_one({"order_id": order_id, "user_id": session["user_id"]})
    if not order:
        return jsonify(success=False, message="Order not found")
    if order.get("order_status") in ("delivered","cancelled"):
        return jsonify(success=False, message="Cannot cancel this order")
    eta   = order.get("estimated_arrival")
    today = datetime.datetime.utcnow().date()
    if eta:
        eta_date = eta.date() if hasattr(eta, "date") else None
        if eta_date and eta_date <= today:
            return jsonify(success=False, message="Cannot cancel — order is arriving today or has already passed")
    orders_col.update_one({"order_id": order_id}, {"$set": {"order_status": "cancelled"}})
    for item in order.get("items", []):
        products_col.update_one({"product_id": item["product_id"]},
                                {"$inc": {"stock_quantity": item["quantity"]}})
    paid_online = order.get("payment_method") == "online"
    amount      = order.get("total_amount", 0)
    msg = (f"Order cancelled. Your refund of ₹{int(amount)} will be credited within 2 business days.") \
          if paid_online else "Order cancelled successfully."

    # ── Send cancellation email ───────────────────────────────────────────────
    user_email = order.get("user_email") or session.get("user_email", "")
    user_name  = order.get("user_name")  or session.get("user_name", "there")
    cancelled_at = datetime.datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")

    items_rows = "".join(
        f"<tr style='border-bottom:1px solid #d4820a22'>"
        f"<td style='padding:9px 12px;color:#e8d5b0;font-size:13px'>{i['name']}</td>"
        f"<td style='padding:9px 12px;color:#e8d5b0;font-size:13px;text-align:center'>{i['quantity']}</td>"
        f"<td style='padding:9px 12px;color:#f5c842;font-size:13px;text-align:right'>&#8377;{i['price']}</td>"
        f"</tr>"
        for i in order.get("items", [])
    )

    if paid_online:
        refund_block = (
            f"<div style='background:#1e2d1e;border:1px solid #2e6b2e;border-radius:10px;"
            f"padding:16px 18px;margin:18px 0'>"
            f"<p style='color:#7ec87e;font-size:12px;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:1px;margin:0 0 10px'>&#128179; Refund Information</p>"
            f"<div style='color:#c8e6c8;font-size:14px;line-height:1.8'>"
            f"Amount: <strong style='color:#6fcf97'>&#8377;{int(amount)}</strong><br>"
            f"Credited to: <strong style='color:#6fcf97'>your original payment method</strong><br>"
            f"Expected within: <strong style='color:#6fcf97'>2 business days</strong>"
            f"</div>"
            f"<p style='color:#a07840;font-size:12px;margin:12px 0 0;line-height:1.6'>"
            f"If your refund is not received within 2 business days, please "
            f"<a href='http://localhost:5000/contact' style='color:#d4820a;text-decoration:none;"
            f"font-weight:700'>contact us</a> and we will resolve it immediately.</p>"
            f"</div>"
        )
    else:
        refund_block = (
            f"<div style='background:#2a1200;border:1px solid #d4820a22;border-radius:10px;"
            f"padding:14px 18px;margin:18px 0'>"
            f"<p style='color:#a07840;font-size:14px;margin:0'>"
            f"This was a Cash on Delivery order — no payment was charged.</p>"
            f"</div>"
        )

    cancel_body = (
        f"<p style='color:#e8d5b0;font-size:15px;margin:0 0 6px'>"
        f"Hi <strong style='color:#f5c842'>{user_name}</strong>,</p>"
        f"<p style='color:#e8d5b0;font-size:15px;line-height:1.7;margin:0 0 18px'>"
        f"Your order has been <strong style='color:#f08080'>successfully cancelled</strong> "
        f"as per your request. We're sorry to see it go!</p>"

        f"<table style='width:100%;border-collapse:collapse;background:#2a1200;"
        f"border:1px solid #d4820a33;border-radius:8px;overflow:hidden;margin-bottom:16px'>"
        f"<tr style='background:#3d1c00'>"
        f"<th style='padding:9px 12px;color:#d4820a;font-size:12px;text-align:left;"
        f"text-transform:uppercase;letter-spacing:0.5px'>Product</th>"
        f"<th style='padding:9px 12px;color:#d4820a;font-size:12px;text-align:center;"
        f"text-transform:uppercase;letter-spacing:0.5px'>Qty</th>"
        f"<th style='padding:9px 12px;color:#d4820a;font-size:12px;text-align:right;"
        f"text-transform:uppercase;letter-spacing:0.5px'>Price</th>"
        f"</tr>{items_rows}</table>"

        f"<div style='background:#2a1200;border:1px solid #d4820a22;border-radius:8px;"
        f"padding:12px 16px;margin-bottom:4px'>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Order ID</span>"
        f"<code style='color:#f5c842;font-size:12px'>{order_id}</code>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Order Total</span>"
        f"<span style='color:#e8d5b0;font-size:13px'>&#8377;{int(amount)}</span>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#a07840;font-size:13px'>Cancelled on</span>"
        f"<span style='color:#e8d5b0;font-size:13px'>{cancelled_at}</span>"
        f"</div>"
        f"</div>"

        f"{refund_block}"

        f"<hr style='border:none;border-top:1px solid rgba(212,130,10,0.2);margin:20px 0'>"
        f"<p style='color:#a07840;font-size:13px;line-height:1.6;margin:0'>"
        f"We hope to welcome you back soon with something even sweeter. &#127851;<br>"
        f"<strong style='color:#d4820a'>The ChocoBite Team</strong></p>"
    )

    if user_email:
        send_email(
            user_email,
            f"ChocoBite — Order Cancelled ({'Refund Initiated' if paid_online else 'No Charge'})",
            email_wrap("Order Cancellation Confirmed", cancel_body)
        )

    return jsonify(success=True, message=msg, paid_online=paid_online, amount=amount)



@app.route("/reseed-cat2")
def reseed_cat2():
    products_col.delete_many({"category_id": 2})
    if not categories_col.find_one({"category_id": 2}):
        categories_col.insert_one({"category_id": 2, "category_name": "Choco Powder", "slug": "powder", "description": "Pure cocoa and hot chocolate mixes"})
    now = datetime.datetime.utcnow()
    i_powder = "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500"
    i_dark   = "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500"
    i_spread = "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500"
    i_cocoa2 = "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500"
    def p(name,desc,price,mrp,img,sugarless,stock,rating,weight,tagline,why_this,health_benefits,pack_type,price_per_100g):
        return {"product_id":str(uuid.uuid4()),"category_id":2,"name":name,"description":desc,"price":float(price),"mrp":float(mrp),"tagline":tagline,"why_this":why_this,"health_benefits":health_benefits,"pack_type":pack_type,"price_per_100g":price_per_100g,"image_url":img,"is_sugarless":sugarless,"stock_quantity":stock,"rating":float(rating),"weight":weight,"created_at":now}
    _ph="Pure cocoa powder is one of nature's richest sources of flavonoids — powerful antioxidants that support heart health, improve blood flow and sharpen cognitive function."
    _dh="High-heat roasting unlocks bioactive compounds that support gut microbiome health and reduce inflammation."
    _du="Alkalized cocoa retains smooth flavour while delivering antioxidants and minerals. Its reduced acidity is gentler on digestion."
    _sh="Natural energy-dense breakfast fuel with real nuts and pure cocoa — healthy fats, plant protein and mood-boosting theobromine."
    products_col.insert_many([
        p("The Original Spark","Small-batch pure cocoa powder from finest single-origin cacao. Intensely chocolatey, completely unsweetened.",749,849,i_powder,True,60,4.7,"150g","The raw essence of the ancient bean","Perfect for health-conscious individuals. Small batch keeps volatile antioxidants fresh for daily smoothies or morning elixirs.",_ph,"Small","\u20b9499 / 100g"),
        p("The Sovereign Blend","Gold-standard pure cocoa powder. Cold-pressed, single-origin cacao with uncompromising depth of flavour.",1899,1989,i_cocoa2,True,40,4.9,"450g","The gold standard of pure cocoa","Our most popular size — the pantry essential for those who have traded commercial chocolate for pure, unadulterated wellness.",_ph,"Premium","\u20b9422 / 100g"),
        p("The Eternal Harvest","Full kilogram of finest pure cocoa powder. Designed for high-frequency users and home bakers.",3499,3519,i_powder,True,25,4.8,"1kg","Abundance in every scoop","Best value ensuring you never run out of your sacred daily ingredient.",_ph,"Large","\u20b9349 / 100g"),
        p("The Midnight Roast","Specialized high-heat roasted cocoa powder unlocking bold coffee-like depth. Deep, smoky and dangerously intense.",1599,1699,i_dark,True,35,4.8,"400g","Deep, smoky, and dangerously intense","Through high-heat roasting we've unlocked bold coffee-like depth. Buy this if you love dark bittersweet flavours in cakes or an intense warming cup of cocoa.",_dh,"Premium","\u20b9399 / 100g"),
        p("The Velvet Royal","Alkalized to perfection. Dutch-process cocoa yielding deep dark colour and smooth mellow flavour.",1499,1699,i_cocoa2,True,30,4.7,"400g","Sophistication in every silken drop","The baker's secret — yields deep dark colour and smooth flavour that blends instantly. Best for professional-grade puddings and frostings.",_du,"Premium","\u20b9374 / 100g"),
        p("The Gilded Forest","Luxurious chocolate breakfast cream with slow-roasted hazelnuts and premium cocoa. Free from waxy commercial fats.",899,999,i_spread,False,45,4.6,"350g","A classic romance of roasted nuts and silk","High percentage of slow-roasted hazelnuts and premium cocoa. Decadent energy-dense breakfast without waxy fats of commercial brands.",_sh,"Premium","\u20b9257 / 100g"),
        p("The Earth and Embers Paste","Protein-rich chocolate breakfast cream of deep-roasted peanuts blended with signature cocoa.",649,669,i_spread,False,50,4.5,"350g","Robust energy meets dark indulgence","Power breakfast — protein-rich spread for sustained fuel. Perfect on sourdough or oatmeal.",_sh,"Premium","\u20b9185 / 100g"),
    ])
    return "<h2 style='font-family:sans-serif;color:#2d7a4f'>&#10003; Choco Powder &mdash; 7 products inserted!</h2><p style='font-family:sans-serif'><a href='/products?cat=powder'>View Products &rarr;</a></p>"


@app.route("/reseed-cat3")
def reseed_cat3():
    products_col.delete_many({"category_id": 3})
    if not categories_col.find_one({"category_id": 3}):
        categories_col.insert_one({"category_id": 3, "category_name": "Flavoured Chocolates", "slug": "flavoured", "description": "Exotic flavour-infused premium chocolate bars"})
    now = datetime.datetime.utcnow()
    i1="https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500"
    i2="https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500"
    i3="https://images.unsplash.com/photo-1612203985729-70726954388c?w=500"
    i4="https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500"
    def p(name,desc,price,mrp,img,sugarless,stock,rating,weight,tagline,why_this,health_benefits,pack_type,price_per_100g):
        return {"product_id":str(uuid.uuid4()),"category_id":3,"name":name,"description":desc,"price":float(price),"mrp":float(mrp),"tagline":tagline,"why_this":why_this,"health_benefits":health_benefits,"pack_type":pack_type,"price_per_100g":price_per_100g,"image_url":img,"is_sugarless":sugarless,"stock_quantity":stock,"rating":float(rating),"weight":weight,"created_at":now}
    _sh="Crafted from ethically sourced cacao rich in flavonoids and theobromine — supporting heart health, enhancing mood and providing calm focused energy."
    _gh="Each gourmet filled chocolate combines premium chocolate with natural fillings — real nuts, fruit pulp and caramel — delivering healthy fats and antioxidants."
    _rh="Our global specialty series uses premium single-origin cacao and natural inclusions, delivering the full antioxidant and mineral profile of fine dark chocolate."
    _bh="Bite-sized doesn't mean less quality. Every piece uses the same premium tempered chocolate as our full bars, delivering full flavonoid benefit in a snackable format."
    _ph="Premium chocolate rich in cocoa butter supports mood and provides natural energy — far healthier than artificially flavoured mass-market candy."
    products_col.insert_many([
        p("Velvet Milk","High-cocoa butter milk chocolate bar that melts instantly. Creamy, nostalgic, premium.",899,999,i2,False,50,4.8,"250g","The silk of the ancient kings","High-cocoa butter milk chocolate that melts instantly — creamy nostalgic experience avoiding the sugar-heavy profile of commercial bars.",_sh,"Premium","\u20b9359 / 100g"),
        p("Velvet Milk Sugar-Free","All the silk of classic Velvet Milk, sweetened only with natural stevia. Zero compromise on texture or flavour.",899,999,i2,True,45,4.7,"250g","The silk of the ancient kings","High-cocoa butter milk chocolate that melts instantly — creamy nostalgic experience avoiding the sugar-heavy profile of commercial bars.",_sh,"Premium","\u20b9359 / 100g"),
        p("Dark Bliss","Crafted with 75% Criollo cacao — complex, fruit-forward bitterness. Ultimate health-conscious indulgence.",899,999,i1,False,40,4.9,"250g","A deep plunge into the heart of the bean","75% Criollo offers complex fruit-forward bitterness — the ultimate health-conscious indulgence for true dark chocolate lovers.",_sh,"Premium","\u20b9359 / 100g"),
        p("Dark Bliss Sugar-Free","75% Criollo dark bar sweetened purely with stevia. Uncompromising depth and zero sugar.",899,999,i1,True,38,4.9,"250g","A deep plunge into the heart of the bean","75% Criollo offers complex fruit-forward bitterness — the ultimate health-conscious indulgence for true dark chocolate lovers.",_sh,"Premium","\u20b9359 / 100g"),
        p("White Elegance","Real white chocolate with deodorized cocoa butter — no fillers. Delicate, floral, perfect with berries or light teas.",899,999,i3,False,35,4.6,"250g","The pure ivory of the cocoa flower","Real white chocolate made with deodorized cocoa butter and no fillers. Delicate, floral, perfect for pairing with berries or light teas.",_sh,"Premium","\u20b9359 / 100g"),
        p("Caramel Kiss","Liquid salted caramel that stays liquid at room temperature inside premium chocolate. Perfect sweet-salty-bitter balance.",1049,1500,i4,False,45,4.8,"250g","Liquid gold wrapped in dark chocolate","Liquid gold wrapped in salted caramel staying liquid at room temperature. Perfect balance of sweet, salty, and bitter for a mid-day luxury break.",_gh,"Premium","\u20b9419 / 100g"),
        p("Nutty Crunch","Slow-roasted almonds and cashews in premium dark chocolate. High-protein, satisfying, substantial bite.",1049,1500,i1,False,40,4.7,"250g","A rhythmic dance of earth and cocoa","Packed with slow-roasted almonds and cashews — high-protein satisfying texture for those who love a noisy and substantial bite.",_gh,"Premium","\u20b9419 / 100g"),
        p("Hazel Hug","Gianduja-style smooth hazelnut-paste center. Nutty, velvety — the comfort-food version of premium chocolate.",1049,1500,i2,False,42,4.8,"250g","The warm embrace of the forest floor","Smooth gianduja-style center offering a nutty, velvety finish — the comfort-food version of premium chocolate.",_gh,"Premium","\u20b9419 / 100g"),
        p("Jelly Joy","Real fruit-pulp jelly centers inside rich dark chocolate. Tart, refreshing, no synthetic flavours.",1049,1500,i3,False,38,4.6,"250g","A burst of sunlight in every dark shell","Real fruit-pulp jelly centers (not synthetic) providing tart refreshing contrast — a favourite for children and adventurous palates.",_gh,"Premium","\u20b9419 / 100g"),
        p("Kunafa","Toasted vermicelli and pistachio butter inside premium chocolate. Middle Eastern inspired, world-class texture.",1299,1399,i4,False,30,4.9,"250g","The crunch of the desert, the soul of the bean","Inspired by the Middle East — toasted vermicelli and pistachio butter offering a world-class texture profile.",_rh,"Premium","\u20b9519 / 100g"),
        p("Gold Dusk","Caramelized blonde chocolate with edible gold dust. High-impact gift that looks as expensive as it tastes.",1299,1399,i3,False,28,4.8,"250g","Ancient wealth, edible at last","Caramelized blonde chocolate with shimmer of edible gold dust — buy when you need a high-impact gift that looks as expensive as it tastes.",_rh,"Premium","\u20b9519 / 100g"),
        p("Gold Dusk Sugar-Free","Iconic blonde caramelized chocolate with edible gold dust — crafted without sugar. All shimmer, no guilt.",1299,1399,i3,True,25,4.7,"250g","Ancient wealth, edible at last","Caramelized blonde chocolate with shimmer of edible gold dust — buy when you need a high-impact gift that looks as expensive as it tastes.",_rh,"Premium","\u20b9519 / 100g"),
        p("Mint Whisper","Organic peppermint oil in premium dark chocolate. Clean cooling finish that aids digestion.",1299,1399,i1,False,32,4.7,"250g","The cool breath of the jungle night","Infused with organic peppermint oil (not essence) — clean cooling finish aiding digestion, perfect post-dinner palate cleanser.",_rh,"Premium","\u20b9519 / 100g"),
        p("Chocorolles","Thin rolled wafers coated in premium cocoa. Light, airy, perfect for snacking.",799,899,i4,False,55,4.6,"250g","Twisted layers of endless indulgence","Thin rolled wafers coated in premium cocoa — light, airy, perfect for snacking while working or reading.",_bh,"Small","\u20b9319 / 100g"),
        p("Chocoballs","Solid bite-sized spheres of perfectly tempered chocolate. Durable, easy to share, slow satisfying melt.",799,899,i2,False,60,4.5,"250g","The spherical heart of the cocoa ritual","Solid bite-sized spheres of tempered chocolate — durable, easy to share, offering slow satisfying melt-down compared to flat bars.",_bh,"Small","\u20b9319 / 100g"),
        p("Mini-Velvet","Premium milk chocolate pocket pack. Silky, creamy, far superior to mass-market candy.",99,99,i2,False,100,4.7,"40g","A little square of silken clouds","Perfect proportion for a small reward — high-quality milk chocolate melting better than mass-market candy, teaching kids what real chocolate tastes like.",_ph,"Pocket Pack","\u20b9247 / 100g"),
        p("Berry Burst","Pocket-sized real forest-fruit jelly inside rich chocolate shell. Chewy, fun, party-in-a-pack.",99,99,i3,False,100,4.6,"40g","A tiny explosion of forest fruit","Children love the contrast of a chewy-filled bite that feels like a party in a small pack.",_ph,"Pocket Pack","\u20b9247 / 100g"),
        p("Magic Bean","Milder 50-60% dark chocolate pocket bar — perfect introduction to cocoa's health benefits.",99,99,i1,False,100,4.5,"40g","A milder dark for little adventurers","Milder dark chocolate (50-60%) to introduce children to cocoa's health benefits without intense bitterness of 75% bars.",_ph,"Pocket Pack","\u20b9247 / 100g"),
        p("Honey Crunch","Premium chocolate with honey-infused honeycomb bits. Snap, crackle and pop interactive experience.",99,99,i4,False,100,4.8,"40g","Golden sparkles in every bite","Honey-infused honeycomb bits create a snap, crackle, pop effect — an interactive joyful experience for kids.",_ph,"Pocket Pack","\u20b9247 / 100g"),
        p("White Blossom","Mini white chocolate pocket bar — naturally sweet, creamy, real deodorized cocoa butter.",99,99,i3,False,100,4.6,"40g","Sweet, snowy, and purely magical","Naturally sweet and creamy — white chocolate favourite among young children, guaranteed best-seller for the school-break crowd.",_ph,"Pocket Pack","\u20b9247 / 100g"),
        p("The Discovery Coin","Gold-foil wrapped chocolate coin — a tiny history lesson in every pocket.",40,40,i4,False,200,4.9,"15g","Unearth the gold of the ancients","Not just candy — a tiny history lesson. Most affordable way for a child to experience premium cocoa. Gold foil makes it feel like a reward from a lost civilization.",_ph,"Pocket Pack","\u20b9266 / 100g"),
    ])
    return "<h2 style='font-family:sans-serif;color:#2d7a4f'>&#10003; Flavoured Chocolates &mdash; all 19 products inserted!</h2><p style='font-family:sans-serif'><a href='/products?cat=flavoured'>View Products &rarr;</a></p>"


@app.route("/debug-reset")
def debug_reset():
    email = request.args.get("email","").strip().lower()
    pw    = request.args.get("pw","").strip()
    if not email or not pw: return "Usage: /debug-reset?email=X&pw=Y"
    user = users_col.find_one({"email": email})
    if not user: return f"No user found for: {email}"
    new_hash = generate_password_hash(pw, method="pbkdf2:sha256")
    result = users_col.update_one({"_id": user["_id"]}, {"$set": {"password_hash": new_hash}})
    check = check_password_hash(new_hash, pw)
    return (f"<pre>Email: {email}\nmatched={result.matched_count} modified={result.modified_count}\n"
            f"check_after={check}</pre><b>Password set to: {pw}</b><br><a href='/'>Login now</a>")

# ─── RUN ─────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)  # <-- CHANGE PORT HERE if needed