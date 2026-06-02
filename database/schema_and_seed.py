"""
============================================================
  CHOCOBITE - MongoDB Schema & Seed File
  
  This file:
    1. Defines all collections with validation schemas
    2. Creates indexes (unique, foreign-key-like)
    3. Seeds default categories & sample products
    
  Run ONCE to initialise the database:
      python database/schema_and_seed.py
============================================================
"""

import uuid
import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import CollectionInvalid
from werkzeug.security import generate_password_hash

# ─────────────────────────────────────────────────────────
#  CONNECTION  ← PUT YOUR MONGODB URI / PORT HERE
# ─────────────────────────────────────────────────────────
MONGO_HOST = "cluster-201.c05ha10.mongodb.net"
MONGO_PORT = 27017          # <-- CHANGE PORT HERE if needed (default 27017)

# For MongoDB Atlas replace the line below with:
# MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/chocobite"
MONGO_URI = f"mongodb+srv://Shivani:prabshiv%40297@cluster-201.c05ha10.mongodb.net/chocobite"

DB_NAME = "chocobite"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

print(f"✅ Connected to MongoDB at {MONGO_URI}")


# ═══════════════════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════════════════
def create_collection_safe(name, validator=None):
    """Create collection only if it doesn't exist."""
    try:
        if validator:
            db.create_collection(name, validator=validator)
        else:
            db.create_collection(name)
        print(f"  📁 Created collection: {name}")
    except CollectionInvalid:
        print(f"  ⚠️  Collection already exists (skipping): {name}")


def drop_and_recreate(name):
    """Drop collection completely, then recreate."""
    db[name].drop()
    print(f"  🗑️  Dropped: {name}")


# ═══════════════════════════════════════════════════════
#  1. USERS COLLECTION
#     user_id      : UUID (string, PK)
#     full_name    : string  (varchar)
#     email        : string  (unique, varchar)
#     password_hash: string  (text)
#     otp_code     : string | null  (for password reset)
#     otp_expires  : datetime | null
#     is_verified  : boolean
#     created_at   : datetime
#     cart         : [] embedded cart reference (denormalised for speed)
# ═══════════════════════════════════════════════════════
print("\n[1] Setting up USERS collection...")

user_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "full_name", "email", "password_hash", "is_verified"],
        "properties": {
            "user_id": {
                "bsonType": "string",
                "description": "UUID primary key — required"
            },
            "full_name": {
                "bsonType": "string",
                "maxLength": 150,
                "description": "varchar(150) — required"
            },
            "email": {
                "bsonType": "string",
                "pattern": "^[^@]+@[^@]+\\.[^@]+$",
                "description": "unique varchar — required"
            },
            "password_hash": {
                "bsonType": "string",
                "description": "bcrypt hash — required"
            },
            "otp_code": {
                "bsonType": ["string", "null"],
                "description": "nullable — for password change"
            },
            "otp_expires": {
                "bsonType": ["date", "null"],
                "description": "nullable datetime — OTP expiry"
            },
            "is_verified": {
                "bsonType": "bool",
                "description": "boolean — id_verified"
            },
            "phone": {
                "bsonType": ["string", "null"]
            },
            "address": {
                "bsonType": ["string", "null"]
            },
            "created_at": {
                "bsonType": "date"
            }
        }
    }
}

create_collection_safe("users", user_validator)

# Unique index on email
db.users.create_index([("email", ASCENDING)], unique=True, name="idx_users_email_unique")
# Index on user_id (PK lookup)
db.users.create_index([("user_id", ASCENDING)], unique=True, name="idx_users_user_id")
print("  🔑 Indexes created: email (unique), user_id (unique)")


# ═══════════════════════════════════════════════════════
#  2. CATEGORIES COLLECTION
#     category_id   : int (PK, auto-assigned 1,2,3)
#     category_name : string
#     slug          : string (url-safe name)
#     description   : string
# ═══════════════════════════════════════════════════════
print("\n[2] Setting up CATEGORIES collection...")

category_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["category_id", "category_name"],
        "properties": {
            "category_id": {
                "bsonType": "int",
                "description": "int PK"
            },
            "category_name": {
                "bsonType": "string",
                "description": "Category display name"
            },
            "slug": {
                "bsonType": "string",
                "description": "URL-safe identifier e.g. seeds, powder, flavoured"
            },
            "description": {
                "bsonType": ["string", "null"]
            }
        }
    }
}

create_collection_safe("categories", category_validator)
db.categories.create_index([("category_id", ASCENDING)], unique=True, name="idx_cat_id")
db.categories.create_index([("slug", ASCENDING)], unique=True, name="idx_cat_slug")


# ═══════════════════════════════════════════════════════
#  3. PRODUCTS COLLECTION
#     product_id    : UUID string (PK)
#     category_id   : int (FK → categories.category_id)
#     name          : string (varchar)
#     description   : string (text)
#     price         : decimal (stored as float)
#     image_url     : string (text)
#     is_sugarless  : boolean
#     stock_quantity: int
#     rating        : float (avg customer rating)
#     weight        : string (e.g. "200g")
#     created_at    : datetime
# ═══════════════════════════════════════════════════════
print("\n[3] Setting up PRODUCTS collection...")

product_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["product_id", "category_id", "name", "price", "is_sugarless", "stock_quantity"],
        "properties": {
            "product_id": {
                "bsonType": "string",
                "description": "UUID PK"
            },
            "category_id": {
                "bsonType": "int",
                "description": "FK → categories.category_id"
            },
            "name": {
                "bsonType": "string",
                "maxLength": 200,
                "description": "varchar(200)"
            },
            "description": {
                "bsonType": ["string", "null"],
                "description": "text"
            },
            "price": {
                "bsonType": ["double", "decimal"],
                "minimum": 0,
                "description": "decimal — product price in INR"
            },
            "image_url": {
                "bsonType": ["string", "null"],
                "description": "text — URL to product image"
            },
            "is_sugarless": {
                "bsonType": "bool",
                "description": "boolean — true if sugar-free"
            },
            "stock_quantity": {
                "bsonType": "int",
                "minimum": 0,
                "description": "int — units in stock"
            },
            "rating": {
                "bsonType": ["double", "null"],
                "minimum": 0,
                "maximum": 5
            },
            "weight": {
                "bsonType": ["string", "null"]
            },
            "created_at": {
                "bsonType": ["date", "null"]
            }
        }
    }
}

create_collection_safe("products", product_validator)
db.products.create_index([("product_id", ASCENDING)], unique=True, name="idx_product_id")
db.products.create_index([("category_id", ASCENDING)], name="idx_product_category")
db.products.create_index([("is_sugarless", ASCENDING)], name="idx_product_sugarless")
# Text index for search
db.products.create_index([("name", "text"), ("description", "text")], name="idx_product_text_search")
print("  🔑 Indexes: product_id, category_id, is_sugarless, text search")


# ═══════════════════════════════════════════════════════
#  4. CART COLLECTION
#     cart_id    : UUID string (PK)
#     user_id    : string (FK → users.user_id)
#     product_id : string (FK → products.product_id)
#     quantity   : int
#     status     : enum ['active', 'saved_for_later']
#     added_at   : datetime
# ═══════════════════════════════════════════════════════
print("\n[4] Setting up CART collection...")

cart_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["cart_id", "user_id", "product_id", "quantity", "status"],
        "properties": {
            "cart_id": {
                "bsonType": "string",
                "description": "UUID PK"
            },
            "user_id": {
                "bsonType": "string",
                "description": "FK → users.user_id"
            },
            "product_id": {
                "bsonType": "string",
                "description": "FK → products.product_id"
            },
            "quantity": {
                "bsonType": "int",
                "minimum": 1,
                "description": "int — must be ≥ 1"
            },
            "status": {
                "bsonType": "string",
                "enum": ["active", "saved_for_later"],
                "description": "enum: active | saved_for_later"
            },
            "added_at": {
                "bsonType": ["date", "null"]
            }
        }
    }
}

create_collection_safe("cart", cart_validator)
db.cart.create_index([("cart_id", ASCENDING)], unique=True, name="idx_cart_id")
db.cart.create_index([("user_id", ASCENDING)], name="idx_cart_user")
db.cart.create_index([("user_id", ASCENDING), ("status", ASCENDING)], name="idx_cart_user_status")
# Prevent duplicate product in same user's active cart
db.cart.create_index(
    [("user_id", ASCENDING), ("product_id", ASCENDING), ("status", ASCENDING)],
    unique=True,
    name="idx_cart_user_product_status_unique"
)
print("  🔑 Indexes: cart_id, user_id, user+product+status (unique)")


# ═══════════════════════════════════════════════════════
#  5. ORDERS COLLECTION
#     order_id         : UUID string (PK)
#     user_id          : string (FK → users.user_id)
#     items            : array of {product_id, name, price, quantity}
#     total_amount     : decimal
#     payment_method   : enum ['online', 'cod']
#     order_status     : enum ['processing', 'shipped', 'delivered']
#     delivery_address : string
#     booked_at        : timestamp (created_at)
#     estimated_arrival: timestamp
#     razorpay_order_id: string | null
#     razorpay_payment_id: string | null
# ═══════════════════════════════════════════════════════
print("\n[5] Setting up ORDERS collection...")

order_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["order_id", "user_id", "items", "total_amount", "payment_method", "order_status", "booked_at"],
        "properties": {
            "order_id": {
                "bsonType": "string",
                "description": "UUID PK"
            },
            "user_id": {
                "bsonType": "string",
                "description": "FK → users.user_id"
            },
            "items": {
                "bsonType": "array",
                "description": "array of ordered products",
                "items": {
                    "bsonType": "object",
                    "required": ["product_id", "name", "price", "quantity"],
                    "properties": {
                        "product_id": {"bsonType": "string"},
                        "name":       {"bsonType": "string"},
                        "price":      {"bsonType": ["double", "decimal"]},
                        "quantity":   {"bsonType": "int"}
                    }
                }
            },
            "total_amount": {
                "bsonType": ["double", "decimal"],
                "minimum": 0,
                "description": "decimal — total in INR"
            },
            "payment_method": {
                "bsonType": "string",
                "enum": ["online", "cod"],
                "description": "enum: online | cod"
            },
            "order_status": {
                "bsonType": "string",
                "enum": ["processing", "shipped", "delivered"],
                "description": "enum: processing | shipped | delivered"
            },
            "delivery_address": {
                "bsonType": ["string", "null"]
            },
            "booked_at": {
                "bsonType": "date",
                "description": "timestamp — when order was placed"
            },
            "estimated_arrival": {
                "bsonType": ["date", "null"],
                "description": "timestamp — expected delivery"
            },
            "razorpay_order_id":   {"bsonType": ["string", "null"]},
            "razorpay_payment_id": {"bsonType": ["string", "null"]}
        }
    }
}

create_collection_safe("orders", order_validator)
db.orders.create_index([("order_id", ASCENDING)], unique=True, name="idx_order_id")
db.orders.create_index([("user_id", ASCENDING)], name="idx_order_user")
db.orders.create_index([("booked_at", DESCENDING)], name="idx_order_date")
print("  🔑 Indexes: order_id, user_id, booked_at")


# ═══════════════════════════════════════════════════════
#  6. FEEDBACK COLLECTION
#     feedback_id : UUID string (PK)
#     user_id     : string (FK → users.user_id)
#     product_id  : string (FK → products.product_id)
#     comment     : string (text)
#     rating      : int (1–5)
#     created_at  : datetime
# ═══════════════════════════════════════════════════════
print("\n[6] Setting up FEEDBACK collection...")

feedback_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["feedback_id", "user_id", "product_id", "comment", "rating"],
        "properties": {
            "feedback_id": {
                "bsonType": "string",
                "description": "UUID PK"
            },
            "user_id": {
                "bsonType": "string",
                "description": "FK → users.user_id"
            },
            "product_id": {
                "bsonType": "string",
                "description": "FK → products.product_id"
            },
            "comment": {
                "bsonType": "string",
                "description": "text"
            },
            "rating": {
                "bsonType": "int",
                "minimum": 1,
                "maximum": 5,
                "description": "int 1–5"
            },
            "created_at": {
                "bsonType": ["date", "null"]
            }
        }
    }
}

create_collection_safe("feedback", feedback_validator)
db.feedback.create_index([("feedback_id", ASCENDING)], unique=True, name="idx_feedback_id")
db.feedback.create_index([("product_id", ASCENDING)], name="idx_feedback_product")
db.feedback.create_index([("user_id", ASCENDING)], name="idx_feedback_user")
# One review per user per product
db.feedback.create_index(
    [("user_id", ASCENDING), ("product_id", ASCENDING)],
    unique=True,
    name="idx_feedback_user_product_unique"
)
print("  🔑 Indexes: feedback_id, product_id, user+product (unique)")


# ═══════════════════════════════════════════════════════
#  7. CONTACTS COLLECTION  (bonus — contact form)
# ═══════════════════════════════════════════════════════
print("\n[7] Setting up CONTACTS collection...")
create_collection_safe("contacts")
db.contacts.create_index([("created_at", DESCENDING)], name="idx_contact_date")


# ═══════════════════════════════════════════════════════
#  SEED: CATEGORIES  (only if empty)
# ═══════════════════════════════════════════════════════
print("\n─── Seeding CATEGORIES ───")

if db.categories.count_documents({}) == 0:
    categories = [
        {
            "category_id":   1,
            "category_name": "Choco Beans & Chips",
            "slug":          "seeds",
            "description":   "Premium chocolate chips and cacao nibs for baking & snacking"
        },
        {
            "category_id":   2,
            "category_name": "Choco Powder",
            "slug":          "powder",
            "description":   "Pure cocoa and hot chocolate mixes for beverages & baking"
        },
        {
            "category_id":   3,
            "category_name": "Flavoured Chocolates",
            "slug":          "flavoured",
            "description":   "Exotic flavour-infused premium chocolate bars & confections"
        },
    ]
    db.categories.insert_many(categories)
    print(f"  ✅ Inserted {len(categories)} categories")
else:
    print("  ⚠️  Categories already seeded — skipping")


# ═══════════════════════════════════════════════════════
#  SEED: PRODUCTS  (only if empty)
# ═══════════════════════════════════════════════════════
print("\n─── Seeding PRODUCTS ───")

if db.products.count_documents({}) == 0:
    now = datetime.datetime.utcnow()

    products = [
        # ── Category 1: Choco Beans & Chips (category_id=1) ──────────────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "Dark Choco Chips",
            "description":    "Premium dark chocolate chips perfect for baking. Rich, intense flavour with 70% cocoa content.",
            "price":          149.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   False,
            "stock_quantity": 50,
            "rating":         4.5,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "Milk Choco Chips",
            "description":    "Creamy milk chocolate chips with a smooth melt. Great for cookies and desserts.",
            "price":          129.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   False,
            "stock_quantity": 45,
            "rating":         4.3,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "White Choco Chips",
            "description":    "Luxurious white chocolate chips with hints of vanilla. Perfect for muffins and cakes.",
            "price":          139.00,
            "image_url":      "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500",
            "is_sugarless":   False,
            "stock_quantity": 30,
            "rating":         4.2,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "Ruby Choco Chips",
            "description":    "Rare ruby cocoa chips with naturally fruity berry notes. A unique baking experience.",
            "price":          199.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   False,
            "stock_quantity": 20,
            "rating":         4.7,
            "weight":         "150g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "Sugar-Free Dark Chips",
            "description":    "Zero-sugar dark chocolate chips made with stevia. Ideal for diabetics and keto diets.",
            "price":          219.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   True,
            "stock_quantity": 35,
            "rating":         4.4,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "Raw Cacao Nibs",
            "description":    "Pure crushed cacao beans — intensely chocolatey superfood topping, naturally unsweetened.",
            "price":          179.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   True,
            "stock_quantity": 0,
            "rating":         4.1,
            "weight":         "100g",
            "created_at":     now
        },

        # ── Category 2: Choco Powder (category_id=2) ─────────────────────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "Dutch Cocoa Powder",
            "description":    "Smooth Dutch-processed cocoa powder with deep color and mild flavour. Ideal for hot chocolate.",
            "price":          189.00,
            "image_url":      "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500",
            "is_sugarless":   False,
            "stock_quantity": 60,
            "rating":         4.6,
            "weight":         "250g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "Raw Organic Cacao Powder",
            "description":    "Cold-pressed raw cacao with antioxidants intact. Intense natural chocolate flavour, no sugar.",
            "price":          229.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   True,
            "stock_quantity": 40,
            "rating":         4.4,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "Sugar-Free Cocoa Mix",
            "description":    "Pure unsweetened cocoa powder. Perfect for diabetics and health-conscious bakers.",
            "price":          209.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   True,
            "stock_quantity": 35,
            "rating":         4.3,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "Premium Hot Choco Mix",
            "description":    "Instant gourmet hot chocolate mix with milk powder, vanilla and premium cocoa. Sweetened.",
            "price":          249.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   False,
            "stock_quantity": 55,
            "rating":         4.8,
            "weight":         "300g",
            "created_at":     now
        },

        # ── Category 3: Flavoured Chocolates (category_id=3) ─────────────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Salted Caramel Dark",
            "description":    "Rich dark chocolate bar with a gooey salted caramel center. An indulgent treat.",
            "price":          299.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   False,
            "stock_quantity": 25,
            "rating":         4.9,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Hazelnut Praline",
            "description":    "Classic Belgian-style milk chocolate filled with crunchy hazelnut praline.",
            "price":          349.00,
            "image_url":      "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500",
            "is_sugarless":   False,
            "stock_quantity": 20,
            "rating":         4.8,
            "weight":         "120g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Mint Dark Chocolate",
            "description":    "Refreshing peppermint infused into 65% dark chocolate. Cool and intense.",
            "price":          279.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   False,
            "stock_quantity": 30,
            "rating":         4.5,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Sugar-Free Dark 85%",
            "description":    "Intensely dark 85% cocoa bar sweetened only with stevia. For true dark chocolate lovers.",
            "price":          319.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   True,
            "stock_quantity": 22,
            "rating":         4.6,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Orange Zest Chocolate",
            "description":    "Real orange peel pieces in silky dark chocolate. A fruity, zesty delight.",
            "price":          269.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   False,
            "stock_quantity": 15,
            "rating":         4.4,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Chilli Dark Chocolate",
            "description":    "Dark chocolate with a surprise chilli kick. Bold and adventurous — sugar-free variant.",
            "price":          289.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   True,
            "stock_quantity": 18,
            "rating":         4.3,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "Strawberry White Choc",
            "description":    "Freeze-dried strawberry pieces in creamy white chocolate. Sweet and fruity.",
            "price":          319.00,
            "image_url":      "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500",
            "is_sugarless":   False,
            "stock_quantity": 0,
            "rating":         4.6,
            "weight":         "100g",
            "created_at":     now
        },

        # ════════════════════════════════════════════════════════
        # GLORYBEAN PRODUCT LINE — across all 3 categories
        # All product names begin with "GloryBean" as specified.
        # About page URL: /about-product/<product_id>
        # ════════════════════════════════════════════════════════

        # ── GloryBean × Category 1: Choco Beans & Chips ──────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "GloryBean Original",   # ← CHANGE NAME HERE
            "description":    "GloryBean's signature whole roasted cacao beans coated in smooth "
                              "milk chocolate. A satisfying crunch with a deep cocoa centre. "
                              "Perfect snack straight from the bag.",
            "price":          189.00,                 # ← CHANGE PRICE HERE
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   False,
            "stock_quantity": 60,
            "rating":         4.6,
            "weight":         "150g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "GloryBean Dark Roast",
            "description":    "Bold, deeply roasted cacao beans enrobed in rich 70% dark "
                              "chocolate. Intense flavour, satisfying crunch. For serious "
                              "chocolate lovers.",
            "price":          219.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   False,
            "stock_quantity": 45,
            "rating":         4.8,
            "weight":         "150g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    1,
            "name":           "GloryBean Sugar-Free",
            "description":    "All the glory of GloryBean Original — zero sugar. Roasted cacao "
                              "beans coated in stevia-sweetened dark chocolate. Keto-friendly.",
            "price":          239.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   True,
            "stock_quantity": 35,
            "rating":         4.5,
            "weight":         "150g",
            "created_at":     now
        },

        # ── GloryBean × Category 2: Choco Powder ─────────────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "GloryBean Cacao Powder",
            "description":    "Cold-pressed raw cacao powder from GloryBean's single-origin "
                              "farms. Intensely chocolatey, packed with antioxidants. No sugar.",
            "price":          249.00,
            "image_url":      "https://images.unsplash.com/photo-1612203985729-70726954388c?w=500",
            "is_sugarless":   True,
            "stock_quantity": 50,
            "rating":         4.7,
            "weight":         "200g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    2,
            "name":           "GloryBean Hot Mix",
            "description":    "GloryBean's premium instant hot chocolate mix. Rich cocoa, "
                              "creamy milk powder and a hint of vanilla — just add hot water.",
            "price":          269.00,
            "image_url":      "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500",
            "is_sugarless":   False,
            "stock_quantity": 55,
            "rating":         4.6,
            "weight":         "250g",
            "created_at":     now
        },

        # ── GloryBean × Category 3: Flavoured Chocolates ─────
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "GloryBean Classic Bar",
            "description":    "GloryBean's iconic smooth milk chocolate bar. Whole milk, "
                              "premium cocoa butter. Melts perfectly — the classic you love.",
            "price":          229.00,
            "image_url":      "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=500",
            "is_sugarless":   False,
            "stock_quantity": 40,
            "rating":         4.8,
            "weight":         "100g",
            "created_at":     now
        },
        {
            "product_id":     str(uuid.uuid4()),
            "category_id":    3,
            "name":           "GloryBean Hazel Crunch",
            "description":    "Whole roasted hazelnuts embedded in GloryBean's 60% dark "
                              "chocolate. Stunning crunch-to-melt contrast.",
            "price":          299.00,
            "image_url":      "https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=500",
            "is_sugarless":   False,
            "stock_quantity": 30,
            "rating":         4.9,
            "weight":         "100g",
            "created_at":     now
        },
    ]

    db.products.insert_many(products)
    print(f"  ✅ Inserted {len(products)} products")
    sugarless_count = sum(1 for p in products if p["is_sugarless"])
    print(f"     • {sugarless_count} sugar-free  |  {len(products)-sugarless_count} with sugar")
else:
    print("  ⚠️  Products already seeded — skipping")


# ═══════════════════════════════════════════════════════
#  PRINT SUMMARY
# ═══════════════════════════════════════════════════════
print("\n" + "═"*55)
print("  ✅  CHOCOBITE DATABASE INITIALISATION COMPLETE")
print("═"*55)
print(f"  Database  : {DB_NAME}")
print(f"  Host      : {MONGO_HOST}:{MONGO_PORT}")
print()
for col in ["users", "categories", "products", "cart", "orders", "feedback", "contacts"]:
    count = db[col].count_documents({})
    print(f"  {col:<14} → {count:>3} documents")
print("═"*55)

client.close()