"""
seasonal_recommender.py
──────────────────────────────────────────────────────────────────────────────
Algorithm: Seasonal Product Recommender using KMeans + Purchase Frequency

How it works:
1. Pull all non-cancelled orders from MongoDB
2. For each product, count purchases per season (Summer/Monsoon/Autumn/Winter)
3. Build feature matrix: [season_purchase_count, overall_popularity, rating]
4. KMeans (k=3) clusters products into:
      Cluster 0 — High sellers     → lower discount (14–17%), already popular
      Cluster 1 — Medium sellers   → medium discount (18–20%)
      Cluster 2 — Low sellers      → highest discount (21–24%), needs boost
5. Pick top N products for current season mixing all 3 clusters
6. As more orders arrive → re-run clustering → offers adapt automatically
7. Offers are FIXED per calendar season (cached in DB, refreshed each season)

sklearn components used:
    KMeans         — cluster products by purchase behaviour
    StandardScaler — normalise features before clustering
    (No mixing with non-sklearn approaches — pure sklearn pipeline)
──────────────────────────────────────────────────────────────────────────────
"""

import datetime
import numpy as np

try:
    from sklearn.cluster       import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# ── Season helpers ────────────────────────────────────────────────────────────

SEASON_MONTHS = {
    "Summer":  [3, 4, 5],
    "Monsoon": [6, 7, 8, 9],
    "Autumn":  [10, 11],
    "Winter":  [12, 1, 2],
}

SEASON_EMOJI = {
    "Summer":  "☀️",
    "Monsoon": "🌧️",
    "Autumn":  "🍂",
    "Winter":  "❄️",
}


def get_current_season() -> tuple[str, str]:
    """Returns (season_name, emoji) based on current month."""
    m = datetime.datetime.utcnow().month
    for name, months in SEASON_MONTHS.items():
        if m in months:
            return name, SEASON_EMOJI[name]
    return "Winter", SEASON_EMOJI["Winter"]


def get_season_for_month(month: int) -> str:
    for name, months in SEASON_MONTHS.items():
        if month in months:
            return name
    return "Winter"


# ── Feature extraction ────────────────────────────────────────────────────────

def build_feature_matrix(products: list, orders: list, target_season: str) -> dict:
    """
    For each product build a feature vector:
        [season_qty, total_qty, rating, price_normalised]

    Returns dict: product_id → {"features": [...], "count_this_season": int,
                                 "count_total": int}
    """
    # Count purchases
    season_count = {}   # product_id → qty in target season
    total_count  = {}   # product_id → qty across all seasons

    for order in orders:
        booked = order.get("booked_at")
        if booked:
            month = booked.month if hasattr(booked, "month") else datetime.datetime.utcnow().month
        else:
            month = datetime.datetime.utcnow().month

        order_season = get_season_for_month(month)

        for item in order.get("items", []):
            pid = item.get("product_id", "")
            if not pid or pid.startswith("SEASONAL-"):
                continue
            qty = int(item.get("quantity", 1))
            total_count[pid]  = total_count.get(pid, 0) + qty
            if order_season == target_season:
                season_count[pid] = season_count.get(pid, 0) + qty

    result = {}
    for p in products:
        pid   = p.get("product_id", "")
        sc    = season_count.get(pid, 0)
        tc    = total_count.get(pid, 0)
        rat   = float(p.get("rating", 4.0))
        price = float(p.get("price", 299))
        result[pid] = {
            "product":          p,
            "count_this_season": sc,
            "count_total":       tc,
            "features":          [sc, tc, rat, price],
        }
    return result


# ── Discount calculation ──────────────────────────────────────────────────────

CLUSTER_DISCOUNT_RANGE = {
    0: (14, 17),   # High sellers   — moderate discount
    1: (18, 20),   # Medium sellers — mid discount
    2: (21, 24),   # Low sellers    — high discount (boost)
}


def assign_discount(cluster_label: int, product_id: str) -> int:
    """
    Deterministic discount within the cluster range,
    using product_id as seed so the same product always gets the same %.
    """
    lo, hi = CLUSTER_DISCOUNT_RANGE.get(cluster_label, (14, 20))
    seed   = sum(ord(c) for c in product_id) % (hi - lo + 1)
    return lo + seed


# ── Main recommender ──────────────────────────────────────────────────────────

def get_seasonal_offers(products: list, orders: list, n_offers: int = 7) -> dict:
    """
    Main entry point.

    Parameters
    ----------
    products  : list of product dicts from MongoDB
    orders    : list of non-cancelled order dicts from MongoDB
    n_offers  : number of offers to return (default 7)

    Returns
    -------
    {
        "season":  str,
        "emoji":   str,
        "offers":  [ { product fields + discount + code + similar } ]
    }
    """
    season_name, emoji = get_current_season()

    if not products:
        return {"season": season_name, "emoji": emoji, "offers": []}

    # Build feature data
    feat_data = build_feature_matrix(products, orders, season_name)
    pids      = list(feat_data.keys())
    X         = np.array([feat_data[pid]["features"] for pid in pids], dtype=float)

    # ── sklearn pipeline ─────────────────────────────────────────────────────
    if SKLEARN_AVAILABLE and len(pids) >= 3:
        scaler    = StandardScaler()
        X_scaled  = scaler.fit_transform(X)

        k         = min(3, len(pids))
        kmeans    = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels    = kmeans.fit_predict(X_scaled)

        # Map cluster index to semantic label (sort clusters by mean season count)
        cluster_means = {}
        for label in range(k):
            idxs = [i for i, l in enumerate(labels) if l == label]
            cluster_means[label] = np.mean([X[i][0] for i in idxs])  # season count

        sorted_clusters = sorted(cluster_means, key=lambda c: cluster_means[c], reverse=True)
        # sorted_clusters[0] = highest season count = cluster label 0 (popular)
        remap = {sorted_clusters[i]: i for i in range(k)}
        labels = [remap[l] for l in labels]
    else:
        # Fallback: simple rank-based assignment if sklearn unavailable or too few products
        season_counts = [X[i][0] for i in range(len(pids))]
        ranks         = np.argsort(np.argsort(season_counts))[::-1]
        n             = len(pids)
        labels = [
            0 if ranks[i] < n // 3
            else 1 if ranks[i] < 2 * n // 3
            else 2
            for i in range(n)
        ]

    # Attach cluster labels and compute scores
    for i, pid in enumerate(pids):
        feat_data[pid]["cluster"]  = labels[i]
        feat_data[pid]["discount"] = assign_discount(labels[i], pid)
        # Score: season purchases + rating boost, weighted by cluster
        cluster_boost = {0: 1.2, 1: 1.0, 2: 0.85}.get(labels[i], 1.0)
        feat_data[pid]["score"] = (
            feat_data[pid]["count_this_season"] * cluster_boost
            + float(feat_data[pid]["product"].get("rating", 4.0)) * 2
        )

    # Sort by score descending
    sorted_pids = sorted(pids, key=lambda p: feat_data[p]["score"], reverse=True)

    # Pick n_offers with category diversity
    seen_cats = {}
    selected  = []
    max_per_cat = max(2, n_offers // 3)

    for pid in sorted_pids:
        cat = feat_data[pid]["product"].get("category_id")
        if seen_cats.get(cat, 0) < max_per_cat:
            seen_cats[cat] = seen_cats.get(cat, 0) + 1
            selected.append(pid)
        if len(selected) == n_offers:
            break

    # Fill remaining slots if needed
    if len(selected) < n_offers:
        for pid in sorted_pids:
            if pid not in selected:
                selected.append(pid)
            if len(selected) == n_offers:
                break

    # Build similar products map (same category, not selected)
    selected_set = set(selected)
    cat_pool     = {}
    for p in products:
        pid = p.get("product_id", "")
        if pid not in selected_set:
            cat_pool.setdefault(p.get("category_id"), []).append(p)

    # Build offer list
    offers = []
    for pid in selected:
        d     = feat_data[pid]
        p     = d["product"]
        disc  = d["discount"]
        orig  = float(p.get("price", 299))
        final = round(orig * (1 - disc / 100))
        cat   = p.get("category_id")

        similar = []
        if cat in cat_pool and cat_pool[cat]:
            sim = cat_pool[cat][0]
            similar.append({
                "product_id": sim["product_id"],
                "name":       sim["name"],
                "price":      sim.get("price", 0),
            })

        offers.append({
            "product_id":      pid,
            "name":            p.get("name", ""),
            "tagline":         p.get("tagline") or p.get("description", "")[:65],
            "image_url":       p.get("image_url", ""),
            "price":           orig,
            "final_price":     final,
            "discount":        disc,
            "cluster":         d["cluster"],  # 0=popular,1=medium,2=boost
            "season_orders":   d["count_this_season"],
            "code":            season_name.upper()[:3] + str(disc),
            "category_id":     cat,
            "similar":         similar,
        })

    return {
        "season":    season_name,
        "emoji":     emoji,
        "offers":    offers,
        "algorithm": "KMeans(k=3) + StandardScaler — sklearn",
    }