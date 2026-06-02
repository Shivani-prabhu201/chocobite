// ============================================
//  CHOCOBITE - MAIN JAVASCRIPT
// ============================================

// ─── SESSION STATE ────────────────────────────
let currentUser = null;

// ─── INIT ─────────────────────────────────────
// Clear login form if user navigates back to page with admin session
window.addEventListener('pageshow', function(e) {
    if (e.persisted) {  // browser cached page (back button)
        var emailField = document.getElementById('loginEmail');
        var passField  = document.getElementById('loginPassword');
        if (emailField) emailField.value = '';
        if (passField)  passField.value  = '';
    }
});

document.addEventListener('DOMContentLoaded', async () => {
    // Show login modal with timeout message if redirected from admin
    if (window.location.search.indexOf('admin_timeout=1') !== -1) {
        setTimeout(function() {
            openAuthModal();
            showAuthMessage('Admin session expired — please sign in again.', 'error');
        }, 300);
    }
    await checkLoginStatus();
    updateCartBadge();
    loadFeedbackBadge();
    generateParticles();

    // On non-home pages the navbar should always be visible (not transparent)
    // Home page has a .hero section; all other pages use .page-header
    var isHomePage = document.querySelector('.hero') !== null;
    if (!isHomePage) {
        var nav = document.querySelector('.navbar');
        if (nav) nav.classList.add('opaque');
    }
});

// ─── AUTH FUNCTIONS ───────────────────────────

async function checkLoginStatus() {
    try {
        const res = await fetch('/api/session-status');
        const data = await res.json();
        currentUser = data;
        
        const loginBtn = document.getElementById('loginNavBtn');
        const userMenu = document.getElementById('userMenu');
        const userGreeting = document.getElementById('userGreeting');
        
        if (data.logged_in) {
            if (loginBtn) loginBtn.classList.add('hidden');
            if (userMenu) {
                userMenu.classList.remove('hidden');
                userGreeting.textContent = `Hi, ${data.name.split(' ')[0]}`;
            }
        } else {
            if (loginBtn) loginBtn.classList.remove('hidden');
            if (userMenu) userMenu.classList.add('hidden');
        }
        return data;
    } catch(e) {
        return { logged_in: false };
    }
}

function requireLogin(callback) {
    if (currentUser && currentUser.logged_in) {
        callback();
    } else {
        openAuthModal();
        // Store callback to call after login
        window._pendingAction = callback;
    }
}

function openAuthModal() {
    // Clear credentials every time modal opens (security + UX)
    var emailField = document.getElementById('loginEmail');
    var passField  = document.getElementById('loginPassword');
    if (emailField) emailField.value = '';
    if (passField)  passField.value  = '';
    clearAuthMessage();
    document.getElementById('authOverlay').classList.remove('hidden');
    switchToLogin();
}

function closeAuthModal() {
    document.getElementById('authOverlay').classList.add('hidden');
    clearAuthMessage();
}

// Close modal on overlay click
document.addEventListener('click', (e) => {
    if (e.target.id === 'authOverlay') closeAuthModal();
});

function switchToLogin() {
    setActiveForm('loginForm');
    clearAuthMessage();
}

function switchToRegister() {
    setActiveForm('registerForm');
    clearAuthMessage();
}

function switchToForgot() {
    setActiveForm('forgotForm');
    clearAuthMessage();
}

function setActiveForm(formId) {
    ['loginForm','registerForm','forgotForm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = 'auth-form' + (id === formId ? ' active' : '');
    });
}

function showAuthMessage(msg, type = 'error') {
    const el = document.getElementById('authMessage');
    el.textContent = msg;
    el.className = `auth-message ${type}`;
}

function clearAuthMessage() {
    const el = document.getElementById('authMessage');
    if (el) { el.textContent = ''; el.className = 'auth-message hidden'; }
}

async function submitLogin() {
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;

    if (!email || !password) {
        showAuthMessage('Please enter email and password');
        return;
    }

    showAuthMessage('Logging in...', 'success');

    const res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password})
    });
    const data = await res.json();

    if (data.success) {
        if (data.is_admin) {
            // Admin login — redirect to admin dashboard
            showAuthMessage(`Welcome, ${data.name}! Redirecting to Admin Portal...`, 'success');
            setTimeout(() => { window.location.href = '/admin/dashboard'; }, 800);
        } else {
            // Regular user login
            showAuthMessage(`Welcome back, ${data.name}! 🍫`, 'success');
            setTimeout(async () => {
                closeAuthModal();
                await checkLoginStatus();
                updateCartBadge();
                loadFeedbackBadge();
                if (window._pendingAction) {
                    window._pendingAction();
                    window._pendingAction = null;
                }
            }, 1000);
        }
    } else {
        showAuthMessage(data.message);
    }
}

/* ================================================================
   PASSWORD STRENGTH HELPERS
   ================================================================ */
function pwScore(pw) {
    var s = 0;
    if (pw.length >= 8)           s++;
    if (/[A-Z]/.test(pw))         s++;
    if (/[0-9]/.test(pw))         s++;
    if (/[^A-Za-z0-9]/.test(pw))  s++;
    return s;
}
var PW_COLORS = ['', '#e04040', '#e07840', '#d4820a', '#6fcf97'];
var PW_LABELS = ['', 'Weak', 'Fair', 'Good', 'Strong'];

function renderStrengthUI(pw, barId, labelId, rulesId, lenId, upId, numId, specId) {
    var score = pw ? pwScore(pw) : 0;
    var bar   = document.getElementById(barId);
    var lbl   = document.getElementById(labelId);
    var rules = document.getElementById(rulesId);
    if (!bar) return;
    bar.style.width      = pw ? (score * 25) + '%' : '0';
    bar.style.background = PW_COLORS[score] || '#e04040';
    if (lbl) { lbl.textContent = pw ? PW_LABELS[score] : ''; lbl.style.color = PW_COLORS[score] || ''; }
    if (rules) rules.style.display = pw ? 'block' : 'none';

    function setRule(id, pass) {
        var el = document.getElementById(id);
        if (!el) return;
        var text = el.textContent.slice(2);
        el.style.color   = pass ? '#6fcf97' : '#555';
        el.innerHTML = (pass ? '<span>&#10003;</span>' : '<span>&#9711;</span>') + ' ' + text;
    }
    setRule(lenId,  pw.length >= 8);
    setRule(upId,   /[A-Z]/.test(pw));
    setRule(numId,  /[0-9]/.test(pw));
    setRule(specId, /[^A-Za-z0-9]/.test(pw));
}

function checkRegStrength(pw) {
    renderStrengthUI(pw, 'regStrengthBar', 'regStrengthLabel', 'regStrengthRules',
                     'rr-len', 'rr-up', 'rr-num', 'rr-spec');
    checkRegConfirm();
}
function checkRegConfirm() {
    var pw  = document.getElementById('regPassword') ? document.getElementById('regPassword').value : '';
    var cf  = document.getElementById('regConfirm')  ? document.getElementById('regConfirm').value  : '';
    var el  = document.getElementById('regConfirmMsg');
    if (!el || !cf) { if(el) el.innerHTML=''; return; }
    if (pw === cf) { el.innerHTML = '<span style="color:#6fcf97">&#10003; Passwords match</span>'; }
    else           { el.innerHTML = '<span style="color:#e04040">&#10007; Passwords do not match</span>'; }
}

function checkResetStrength(pw) {
    renderStrengthUI(pw, 'resetStrengthBar', 'resetStrengthLabel', 'resetStrengthRules',
                     'rs-len', 'rs-up', 'rs-num', 'rs-spec');
    checkResetConfirm();
}
function checkResetConfirm() {
    var pw = document.getElementById('newPassword')     ? document.getElementById('newPassword').value     : '';
    var cf = document.getElementById('confirmPassword') ? document.getElementById('confirmPassword').value : '';
    var el = document.getElementById('resetConfirmMsg');
    if (!el || !cf) { if(el) el.innerHTML=''; return; }
    if (pw === cf) { el.innerHTML = '<span style="color:#6fcf97">&#10003; Passwords match</span>'; }
    else           { el.innerHTML = '<span style="color:#e04040">&#10007; Passwords do not match</span>'; }
}

function togglePw(fieldId, btnId) {
    var inp = document.getElementById(fieldId);
    var btn = document.getElementById(btnId);
    if (!inp) return;
    inp.type = inp.type === 'password' ? 'text' : 'password';
    var showing = inp.type === 'text';
    if (btn) {
        btn.classList.toggle('active', showing);
        btn.innerHTML = showing ? '&#128064;' : '&#128065;';
    }
}

function isStrongPassword(pw) {
    return pw.length >= 8 && /[A-Z]/.test(pw) && /[0-9]/.test(pw) && /[^A-Za-z0-9]/.test(pw);
}

async function submitRegister() {
    const name = document.getElementById('regName').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const phone = document.getElementById('regPhone').value.trim();
    const address = document.getElementById('regAddress').value.trim();
    const password = document.getElementById('regPassword').value;

    if (!name || !email || !password) {
        showAuthMessage('Please fill all required fields');
        return;
    }

    if (/[0-9]/.test(name)) {
        showAuthMessage('Name should not contain numbers');
        return;
    }

    if (password.length < 6) {
        showAuthMessage('Password must be at least 6 characters');
        return;
    }

    showAuthMessage('Creating account...', 'success');

    const res = await fetch('/api/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, email, password, phone, address})
    });
    const data = await res.json();

    if (data.success) {
        showAuthMessage(`Account created! Welcome ${data.name}! 🎉`, 'success');
        setTimeout(async () => {
            closeAuthModal();
            await checkLoginStatus();
            updateCartBadge();
            if (window._pendingAction) {
                window._pendingAction();
                window._pendingAction = null;
            }
        }, 1200);
    } else {
        showAuthMessage(data.message);
    }
}

async function submitForgot() {
    const email = document.getElementById('forgotEmail').value.trim();
    if (!email) { showAuthMessage('Please enter your email'); return; }

    showAuthMessage('Sending OTP...', 'success');
    const res = await fetch('/api/forgot-password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email})
    });
    const data = await res.json();
    showAuthMessage(data.message, data.success ? 'success' : 'error');
    if (data.success) {
        document.getElementById('otpSection').classList.remove('hidden');
    }
}

async function submitResetPassword() {
    // Read email from the field — it stays visible even after OTP section opens
    const email       = document.getElementById('forgotEmail').value.trim();
    const otp         = document.getElementById('otpInput').value.trim();
    const newPassword = document.getElementById('newPassword').value;
    const confirmPw   = document.getElementById('confirmPassword')
                        ? document.getElementById('confirmPassword').value
                        : newPassword;  // confirm field may not exist

    if (!email)       { showAuthMessage('Email is missing. Please go back and enter it.', 'error'); return; }
    if (!otp)         { showAuthMessage('Please enter the OTP sent to your email.', 'error'); return; }
    if (!newPassword) { showAuthMessage('Please enter a new password.', 'error'); return; }
    if (newPassword.length < 6) { showAuthMessage('Password must be at least 6 characters.', 'error'); return; }

    showAuthMessage('Updating password...', 'success');

    const res  = await fetch('/api/reset-password', {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({email: email, otp: otp, new_password: newPassword})
    });
    const data = await res.json();

    showAuthMessage(data.message, data.success ? 'success' : 'error');

    if (data.success) {
        // Clear fields
        document.getElementById('forgotEmail').value = '';
        document.getElementById('otpInput').value    = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('otpSection').classList.add('hidden');
        // Switch to login after short delay
        setTimeout(switchToLogin, 2000);
    }
}

async function submitLogout() {
    await fetch('/api/logout', {method: 'POST'});
    currentUser = null;
    await checkLoginStatus();
    showToast('Logged out successfully', 'success');
    updateCartBadge();
    // Reload if on protected page
    if (window.location.pathname === '/cart') {
        location.reload();
    }
}

// Enter key support for login
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const loginForm = document.getElementById('loginForm');
        const regForm = document.getElementById('registerForm');
        if (loginForm && loginForm.classList.contains('active')) submitLogin();
        if (regForm && regForm.classList.contains('active')) submitRegister();
    }
});

// ─── CART ─────────────────────────────────────

async function loadFeedbackBadge() {
    try {
        var r = await fetch('/api/user/my-review-replies');
        var d = await r.json();
        var el = document.getElementById('fbReplyBadge');
        if (el && Array.isArray(d) && d.length > 0) {
            el.textContent = d.length;
            el.style.display = 'inline';
        }
    } catch(e) {}
}

async function updateCartBadge() {
    try {
        const res = await fetch('/api/cart');
        const data = await res.json();
        const count = (data.cart || []).reduce((s, i) => s + i.quantity, 0);
        const badge = document.getElementById('cartBadge');
        if (badge) badge.textContent = count;
    } catch(e) {}
}

// ─── PRODUCT CARD ─────────────────────────────

function createProductCard(product) {
    const pid      = product.product_id || product._id;
    const stockQty = (product.stock_quantity !== undefined) ? product.stock_quantity : (product.stock || 0);
    const oos      = stockQty === 0;
    const stars    = '★'.repeat(Math.floor(product.rating || 4)) + '☆'.repeat(5 - Math.floor(product.rating || 4));
    const imgSrc   = product.image_url || product.image
                     || 'https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=400';

    // Pack type badge — Pocket Pack=★, Premium=crown, Party Pack=L
    const CROWN_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 14" width="16" height="11" fill="#d4820a" style="filter:drop-shadow(0 1px 2px rgba(0,0,0,0.5))"><polygon points="0,14 0,5 5,9 10,0 15,9 20,5 20,14"/></svg>';
    const packInitial = product.pack_type
        ? (product.pack_type === 'Pocket Pack' ? '&#9733;'
         : product.pack_type === 'Premium'     ? CROWN_SVG
         : product.pack_type === 'Party Pack'  ? 'L'
         : product.pack_type.trim().charAt(0).toUpperCase())
        : '';
    const packBadge = packInitial
        ? `<div class="card-pack-badge" title="${product.pack_type}" style="position:absolute;top:8px;right:8px;left:auto;">${packInitial}</div>`
        : '';

    // Sugar-free badge
    const sugarBadge = product.is_sugarless
        ? '<div class="sugarless-badge">Sugar-Free</div>'
        : '<div class="sugarless-badge" style="background:rgba(160,80,10,.85);color:#ffe0b2">Contains Sugar</div>';

    const oosRibbon = oos ? '<div class="out-of-stock-ribbon">Out of Stock</div>' : '';

    // Launch offer — 50% off for first 10 buyers, time-limited
    const lo = product.launch_offer_active;
    const launchBadge = lo
        ? `<div style="position:absolute;top:0;left:0;right:0;background:linear-gradient(135deg,#8b0000,#d4820a);
            color:#fff;font-size:10px;font-weight:700;padding:5px 10px;
            display:flex;justify-content:space-between;align-items:center;z-index:5">
            <span>&#127381; LAUNCH OFFER — 50% OFF</span>
            <span style="color:#ffd700">${product.launch_offer_left || ''} spots left</span>
           </div>`
        : '';
    const launchPrice = lo ? Math.round(product.launch_offer_price) : null;

    // Price block — show launch offer price if active, else MRP strikethrough
    let priceHTML;
    if (lo && launchPrice) {
        // Launch offer active — show offer price prominently
        priceHTML = `
            <div class="card-price-row">
                <span class="card-price" style="color:#f5c842">₹${launchPrice}</span>
                <span class="card-mrp" style="text-decoration:line-through;color:#888">₹${Math.round(product.price)}</span>
                <span class="card-save" style="background:#8b0000;color:#fff;font-size:9px;padding:2px 6px;border-radius:4px">50% OFF</span>
            </div>`;
    } else if (product.mrp && product.mrp > product.price) {
        const save = Math.round(product.mrp - product.price);
        priceHTML = `
            <div class="card-price-row">
                <span class="card-price">₹${Math.round(product.price)}</span>
                <span class="card-mrp">₹${Math.round(product.mrp)}</span>
                <span class="card-save">Save ₹${save}</span>
            </div>
            ${product.price_per_100g ? `<div class="card-per100">${product.price_per_100g}</div>` : ''}`;
    } else {
        priceHTML = `
            <div class="card-price-row">
                <span class="card-price">₹${Math.round(product.price)}</span>
            </div>
            ${product.price_per_100g ? `<div class="card-per100">${product.price_per_100g}</div>` : ''}`;
    }

    // Tagline — shown below name
    const taglineHTML = product.tagline
        ? `<div class="card-tagline">${product.tagline}</div>`
        : '';

    // Weight pill
    const weightHTML = product.weight
        ? `<span class="card-weight-pill">${product.weight}</span>`
        : '';

    return `
        <div class="product-card ${oos ? 'oos' : ''}">

            <div class="product-card-img" onclick="goToAbout('${pid}')" style="cursor:pointer">
                <img src="${imgSrc}" alt="${product.name}"
                     onerror="this.src='https://images.unsplash.com/photo-1606312619070-d48b4c652a52?w=400'">
                ${launchBadge}
                ${oosRibbon}
                ${packBadge}
                ${sugarBadge}
            </div>

            <div class="product-card-body">
                ${weightHTML}
                <div class="product-card-name">${product.name}</div>
                ${taglineHTML}
                ${priceHTML}
                <div class="product-card-rating">${stars} <span style="font-size:.8rem;color:var(--text-muted)">${product.rating || 4.5}</span></div>

                <div class="product-card-btns-new">
                    <button class="btn-about btn-sm" onclick="goToAbout('${pid}')">
                        About Product
                    </button>
                    <button class="btn-sm cart-sm" onclick="quickAddToCart('${pid}')" ${oos ? 'disabled' : ''}>
                        Cart
                    </button>
                    <button class="btn-sm buy-sm" onclick="goToBuyNow('${pid}')" ${oos ? 'disabled' : ''}>
                        Buy Now
                    </button>
                </div>
            </div>
        </div>`;
}

// Navigate to About Product page  →  /about-product/<id>
// NO login required — anyone can view product details freely.
// Login is only required when clicking Cart or Buy inside the page.
// Flask route: about_product() in app.py
// Template:    templates/about_product.html
function goToAbout(id) {
    // No login required — product detail page is public
    window.location.href = `/about-product/${id}`;
}

// Buy Now → goes to about-product page and auto-opens payment modal
function goToBuyNow(id) {
    requireLogin(() => {
        window.location.href = `/about-product/${id}?buy=1`;
    });
}

function goToProduct(id) {
    requireLogin(() => {
        window.location.href = `/product/${id}`;
    });
}

async function quickAddToCart(productId) {
    requireLogin(async () => {
        const res = await fetch('/api/cart/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({product_id: productId, quantity: 1})
        });
        const data = await res.json();
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) updateCartBadge();
    });
}

// ─── TOAST ────────────────────────────────────

let toastTimer;
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.className = 'toast hidden';
    }, 3500);
}

// ─── MOBILE MENU ──────────────────────────────

function toggleMobileMenu() {
    const menu = document.getElementById('mobileMenu');
    if (menu) menu.classList.toggle('hidden');
}

// ─── PARTICLES ────────────────────────────────

function generateParticles() {
    const container = document.getElementById('heroParticles');
    if (!container) return;
    
    const count = 20;
    for (let i = 0; i < count; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        p.style.cssText = `
            left: ${Math.random() * 100}%;
            width: ${4 + Math.random() * 6}px;
            height: ${4 + Math.random() * 6}px;
            animation-duration: ${8 + Math.random() * 12}s;
            animation-delay: ${Math.random() * 8}s;
            opacity: ${0.2 + Math.random() * 0.4};
        `;
        // Some particles are chocolate drops
        if (Math.random() > 0.7) {
            p.style.borderRadius = '50% 50% 50% 0';
            p.style.transform = 'rotate(-45deg)';
            p.style.background = '#6b3500';
        }
        container.appendChild(p);
    }
}

// ── Seasonal Offer Floating Bubble (shown on all pages except customize) ─────
function soDismissBubble(e) {
    e.stopPropagation();
    var b = document.getElementById('soFloatBubble');
    if (b) b.remove();
}

(function soGlobalBubble() {
    // Don't add on customize page (it has its own bubble)
    if (window.location.pathname.indexOf('/customize') !== -1) return;

    // Inject bubble CSS
    if (!document.getElementById('soBubbleStyle')) {
        var st = document.createElement('style');
        st.id  = 'soBubbleStyle';
        st.textContent = [
            '#soFloatBubble{position:fixed;bottom:28px;right:28px;z-index:8888;display:flex;',
            'align-items:center;gap:10px;background:#000;border:1.5px solid #d4820a;',
            'border-radius:50px;padding:10px 18px 10px 14px;cursor:pointer;',
            'box-shadow:0 4px 24px rgba(212,130,10,0.25);transition:transform .2s,box-shadow .2s;',
            'max-width:300px;animation:soBubblePop .5s ease;}',
            '#soFloatBubble:hover{transform:translateY(-3px);box-shadow:0 8px 32px rgba(212,130,10,0.4);}',
            '@keyframes soBubblePop{from{transform:scale(0.6);opacity:0}to{transform:scale(1);opacity:1}}',
            '.so-bubble-emoji{font-size:22px;flex-shrink:0;}',
            '.so-bubble-text{flex:1;min-width:0;}',
            '.so-bubble-title{color:#f5c842;font-size:12px;font-weight:700;',
            'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
            '.so-bubble-sub{color:#a07840;font-size:10px;white-space:nowrap;',
            'overflow:hidden;text-overflow:ellipsis;}',
            '.so-bubble-close{background:none;border:none;color:#a07840;font-size:14px;',
            'cursor:pointer;flex-shrink:0;padding:0 0 0 4px;}'
        ].join('');
        document.head.appendChild(st);
    }

    function buildBubble(offer, season, emoji) {
        var existing = document.getElementById('soFloatBubble');
        if (existing) existing.remove();  // replace if already shown (e.g. after refresh)

        var bubble = document.createElement('div');
        bubble.id  = 'soFloatBubble';
        bubble.innerHTML =
            '<div class="so-bubble-emoji">' + emoji + '</div>' +
            '<div class="so-bubble-text">' +
                '<div class="so-bubble-title">' + offer.discount + '% OFF — ' + offer.name + '</div>' +
                '<div class="so-bubble-sub">' + season + ' Special · Tap to redeem</div>' +
            '</div>' +
            '<button class="so-bubble-close" onclick="soDismissBubble(event)" ' +
                'title="Dismiss">&#10005;</button>';

        bubble.addEventListener('click', function() {
            window.location.href = '/customize?tab=seasonal';
        });
        document.body.appendChild(bubble);
    }

    // Fetch live offers from the ML API — same data users see in customize
    setTimeout(function() {
        if (document.getElementById('soFloatBubble')) return; // already shown
        fetch('/api/seasonal-offers')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var offers = data.offers || [];
                if (!offers.length) return;
                // Pick a random offer from the live ML results
                var idx    = Math.floor(Math.random() * offers.length);
                var offer  = offers[idx];
                var emoji  = data.emoji || '☀️';
                buildBubble(offer, data.season, emoji);
            })
            .catch(function() {
                // API failed silently — don't show bubble rather than show stale data
            });
    }, 1500);
})();