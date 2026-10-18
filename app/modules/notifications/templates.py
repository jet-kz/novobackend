"""
Transactional email templates. Each builder returns (subject, html, text).

Layout is table-based with inline styles so it renders in Gmail/Outlook/Apple Mail.
"""
from html import escape

from app.core import config

BRAND = "#087F5B"
INK = "#17201D"
MUTED = "#66736E"

Email = tuple[str, str, str]


def _url(path: str) -> str:
    return f"{config.FRONTEND_URL}{path}"


def _naira(amount) -> str:
    try:
        return f"₦{float(amount or 0):,.0f}"
    except (TypeError, ValueError):
        return "₦0"


def _layout(title: str, body_html: str, cta: tuple[str, str] | None = None) -> str:
    button = ""
    if cta:
        label, href = cta
        button = (
            f'<tr><td style="padding:8px 32px 28px">'
            f'<a href="{escape(href)}" style="display:inline-block;background:{BRAND};color:#fff;'
            f'text-decoration:none;font-weight:700;font-size:14px;padding:12px 22px;border-radius:8px">'
            f"{escape(label)}</a></td></tr>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#F3F6F5;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:{INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F6F5;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#fff;border-radius:14px;overflow:hidden">
<tr><td style="background:{BRAND};padding:18px 32px">
<span style="color:#fff;font-size:22px;font-weight:800;letter-spacing:-0.5px">novo</span>
</td></tr>
<tr><td style="padding:28px 32px 8px">
<h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;color:{INK}">{escape(title)}</h1>
<div style="font-size:14px;line-height:1.6;color:{INK}">{body_html}</div>
</td></tr>
{button}
<tr><td style="padding:18px 32px;border-top:1px solid #E6ECEA;font-size:12px;line-height:1.5;color:{MUTED}">
Questions? Reply to this email or write to <a href="mailto:{config.MAIL_REPLY_TO}" style="color:{BRAND}">{config.MAIL_REPLY_TO}</a>.<br>
Novo &middot; <a href="{config.FRONTEND_URL}" style="color:{MUTED}">{config.FRONTEND_URL.replace("https://", "")}</a>
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""


def _greeting(name: str | None) -> str:
    return f"Hi {escape(name.split()[0])}," if name and name.strip() else "Hi there,"


def _code_block(code: str) -> str:
    return (
        f'<p style="margin:18px 0;font-size:32px;font-weight:800;letter-spacing:8px;'
        f'color:{BRAND};font-family:Menlo,Consolas,monospace">{escape(code)}</p>'
    )


def _text(*lines: str) -> str:
    return "\n".join(lines + ("", f"Questions? Write to {config.MAIL_REPLY_TO}", "Novo · " + config.FRONTEND_URL))


# ── Account ──────────────────────────────────────────────────────────────────

def verification_code(name: str | None, code: str, minutes: int) -> Email:
    subject = f"{code} is your Novo verification code"
    html = _layout(
        "Verify your email",
        f"<p>{_greeting(name)}</p><p>Enter this code to finish creating your Novo account:</p>"
        f"{_code_block(code)}<p style='color:{MUTED}'>It expires in {minutes} minutes. "
        "If you didn't sign up for Novo, you can ignore this email.</p>",
    )
    text = _text(_greeting(name), "", f"Your Novo verification code is {code}.", f"It expires in {minutes} minutes.")
    return subject, html, text


def password_reset_code(name: str | None, code: str, minutes: int) -> Email:
    subject = f"{code} is your Novo password reset code"
    html = _layout(
        "Reset your password",
        f"<p>{_greeting(name)}</p><p>We received a request to reset your Novo password. Enter this code to choose a new one:</p>"
        f"{_code_block(code)}<p style='color:{MUTED}'>It expires in {minutes} minutes. "
        "If you didn't ask for this, ignore this email &mdash; your password won't change.</p>",
    )
    text = _text(_greeting(name), "", f"Your Novo password reset code is {code}.", f"It expires in {minutes} minutes.",
                 "If you didn't ask for this, ignore this email.")
    return subject, html, text


def password_changed(name: str | None) -> Email:
    subject = "Your Novo password was changed"
    html = _layout(
        "Password changed",
        f"<p>{_greeting(name)}</p><p>The password on your Novo account was just changed.</p>"
        f"<p>If this wasn't you, reset your password right away and contact us at "
        f'<a href="mailto:{config.MAIL_REPLY_TO}" style="color:{BRAND}">{config.MAIL_REPLY_TO}</a>.</p>',
        ("Sign in", _url("/auth")),
    )
    text = _text(_greeting(name), "", "The password on your Novo account was just changed.",
                 f"If this wasn't you, contact {config.MAIL_REPLY_TO} right away.")
    return subject, html, text


_WELCOME = {
    "customer": (
        "Welcome to Novo",
        "Your account is ready. Order food, groceries and pharmacy essentials from stores near you, "
        "and track every delivery live.",
        ("Start ordering", "/"),
    ),
    "merchant_owner": (
        "Welcome to Novo for Business",
        "Your merchant account is ready. Add your menu, set your opening hours and start receiving orders. "
        "Our team reviews new stores before they go live to customers.",
        ("Open merchant dashboard", "/merchant"),
    ),
    "rider": (
        "Welcome to the Novo rider team",
        "Your rider account is ready. Go online in the Rider Hub to start receiving delivery requests near you.",
        ("Open Rider Hub", "/rider"),
    ),
}


def welcome(name: str | None, role: str) -> Email:
    title, blurb, (label, path) = _WELCOME.get(role, _WELCOME["customer"])
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>", (label, _url(path)))
    return title, html, _text(_greeting(name), "", blurb, _url(path))


# ── Orders ───────────────────────────────────────────────────────────────────

def _items_table(items: list[dict]) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 0">{int(i.get("quantity") or 1)}&times; {escape(str(i.get("name") or "Item"))}</td>'
        f'<td align="right" style="padding:6px 0">{_naira(i.get("total"))}</td></tr>'
        for i in items
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;margin:12px 0">{rows}</table>'


def _totals(order: dict) -> str:
    def row(label, value, bold=False):
        weight = "font-weight:800;" if bold else f"color:{MUTED};"
        return f'<tr><td style="padding:3px 0;{weight}">{label}</td><td align="right" style="padding:3px 0;{weight}">{value}</td></tr>'

    lines = row("Subtotal", _naira(order.get("subtotal"))) + row("Delivery", _naira(order.get("delivery_fee")))
    if float(order.get("service_fee") or 0):
        lines += row("Service fee", _naira(order.get("service_fee")))
    if float(order.get("tip") or 0):
        lines += row("Rider tip", _naira(order.get("tip")))
    lines += row("Total", _naira(order.get("total")), bold=True)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;border-top:1px solid #E6ECEA;padding-top:8px">{lines}</table>'


_PAYMENT_LABEL = {"cash": "Cash on delivery", "transfer": "Bank transfer on delivery", "card": "Card", "wallet": "Wallet"}


def order_placed(name: str | None, order: dict, store_name: str, items: list[dict], track_url: str | None = None) -> Email:
    oid = order["id"]
    subject = f"Order {oid} received — {store_name}"
    pay = _PAYMENT_LABEL.get(order.get("payment_method") or "", order.get("payment_method") or "")
    html = _layout(
        "We've got your order",
        f"<p>{_greeting(name)}</p><p>Your order from <strong>{escape(store_name)}</strong> has been sent to the store. "
        f"We'll email you when it's confirmed and when it's on the way.</p>"
        f"{_items_table(items)}{_totals(order)}"
        f"<p style='color:{MUTED};margin-top:14px'>Order {escape(oid)} &middot; {escape(pay)}<br>"
        f"Delivering to {escape(order.get('delivery_address') or '')}</p>",
        ("Track your order", track_url or _url("/orders")),
    )
    text = _text(_greeting(name), "", f"Your order {oid} from {store_name} has been sent to the store.",
                 f"Total: {_naira(order.get('total'))} ({pay})", f"Track it: {track_url or _url('/orders')}")
    return subject, html, text


def payment_received(name: str | None, order_id: str, amount) -> Email:
    subject = f"Payment received for order {order_id}"
    html = _layout(
        "Payment received",
        f"<p>{_greeting(name)}</p><p>We received your payment of <strong>{_naira(amount)}</strong> for order "
        f"<strong>{escape(order_id)}</strong>. The store has been notified.</p>",
        ("Track your order", _url("/orders")),
    )
    return subject, html, _text(_greeting(name), "", f"We received {_naira(amount)} for order {order_id}.")


def merchant_new_order(store_name: str, order: dict, items: list[dict]) -> Email:
    oid = order["id"]
    subject = f"New order {oid} — {_naira(order.get('total'))}"
    pay = _PAYMENT_LABEL.get(order.get("payment_method") or "", order.get("payment_method") or "")
    html = _layout(
        f"New order for {store_name}",
        f"<p>You have a new order waiting for confirmation.</p>{_items_table(items)}{_totals(order)}"
        f"<p style='color:{MUTED};margin-top:14px'>Order {escape(oid)} &middot; {escape(pay)}<br>"
        f"Customer: {escape(order.get('customer_name') or 'Customer')}</p>",
        ("Open orders", _url("/merchant/orders")),
    )
    text = _text(f"New order {oid} for {store_name}.", f"Total: {_naira(order.get('total'))} ({pay})",
                 f"Open orders: {_url('/merchant/orders')}")
    return subject, html, text


_STATUS_COPY = {
    "CONFIRMED": ("Your order is confirmed", "{store} accepted your order and is getting it ready."),
    "PICKED_UP": ("Your order is on the way", "Your rider has picked up your order from {store} and is heading to you."),
    "DELIVERED": ("Your order was delivered", "Your order from {store} has been delivered. Enjoy, and thanks for ordering with Novo!"),
    "CANCELLED": ("Your order was cancelled", "Your order from {store} was cancelled.{reason} If you paid by card, your refund will be processed to the original payment method."),
    "FAILED": ("We couldn't deliver your order", "Your order from {store} couldn't be delivered.{reason} Our support team will reach out to sort it out."),
}


def order_status_update(name: str | None, order_id: str, status: str, store_name: str, reason: str | None = None,
                        show_link: bool = True) -> Email | None:
    copy = _STATUS_COPY.get(status)
    if not copy:
        return None
    title, blurb = copy
    reason_txt = f" Reason: {reason}." if reason else ""
    message = blurb.format(store=store_name, reason=reason_txt)
    subject = f"{title} ({order_id})"
    html = _layout(
        title,
        f"<p>{_greeting(name)}</p><p>{escape(message)}</p><p style='color:{MUTED}'>Order {escape(order_id)}</p>",
        ("View order", _url("/orders")) if show_link else None,
    )
    return subject, html, _text(_greeting(name), "", message, f"Order {order_id}")


def merchant_order_cancelled(store_name: str, order_id: str, reason: str | None) -> Email:
    subject = f"Order {order_id} was cancelled by the customer"
    reason_html = f"<p>Reason given: {escape(reason)}</p>" if reason else ""
    html = _layout(
        "Order cancelled",
        f"<p>Order <strong>{escape(order_id)}</strong> for {escape(store_name)} was cancelled by the customer. "
        f"You don't need to prepare it.</p>{reason_html}",
        ("Open orders", _url("/merchant/orders")),
    )
    return subject, html, _text(f"Order {order_id} for {store_name} was cancelled by the customer.", reason or "")


def rider_job_assigned(name: str | None, order_id: str, store_name: str, store_address: str | None, earnings) -> Email:
    subject = f"Delivery {order_id} assigned to you"
    html = _layout(
        "New delivery assigned",
        f"<p>{_greeting(name)}</p><p>Pick up order <strong>{escape(order_id)}</strong> from "
        f"<strong>{escape(store_name)}</strong>{(' at ' + escape(store_address)) if store_address else ''}. "
        f"Ask the store for the 4-digit pickup code.</p><p>Earnings for this trip: <strong>{_naira(earnings)}</strong></p>",
        ("Open Rider Hub", _url("/rider")),
    )
    return subject, html, _text(_greeting(name), "", f"Pick up order {order_id} from {store_name}.",
                                f"Earnings: {_naira(earnings)}")


# ── Admin actions ────────────────────────────────────────────────────────────

def store_verification(name: str | None, store_name: str, verified: bool) -> Email:
    if verified:
        title = f"{store_name} is live on Novo"
        blurb = "Your store has been approved and customers can now find and order from it."
    else:
        title = f"{store_name} is under review"
        blurb = "Your store has been taken off the customer storefront while our team reviews it. We'll be in touch."
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>", ("Open merchant dashboard", _url("/merchant")))
    return title, html, _text(_greeting(name), "", blurb)


_MERCHANT_STATUS = {
    "active": ("Your Novo merchant account is active", "Your merchant account is active. You can receive and manage orders as normal."),
    "suspended": ("Your Novo merchant account is suspended", "Your merchant account has been suspended and your stores won't receive new orders. Reply to this email to find out more."),
    "pending": ("Your Novo merchant account is under review", "Your merchant account is under review. We'll email you as soon as it's approved."),
}


def merchant_status(name: str | None, status: str) -> Email | None:
    copy = _MERCHANT_STATUS.get(status)
    if not copy:
        return None
    title, blurb = copy
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>", ("Open merchant dashboard", _url("/merchant")))
    return title, html, _text(_greeting(name), "", blurb)


def rider_deactivated(name: str | None) -> Email:
    title = "Your Novo rider account was deactivated"
    blurb = "Your rider account has been deactivated and you won't receive new delivery requests. Reply to this email if you think this is a mistake."
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>")
    return title, html, _text(_greeting(name), "", blurb)


def rider_review(name: str | None, approved: bool, note: str | None) -> Email:
    if approved:
        title = "You're approved to ride with Novo"
        blurb = "Your rider account has been approved. Open the Rider Hub and go online to start receiving deliveries."
    else:
        title = "Your Novo rider application needs attention"
        blurb = "We couldn't approve your rider account yet."
    note_html = f"<p><strong>Note from our team:</strong> {escape(note)}</p>" if note else ""
    if not approved:
        note_html += "<p>Update your details in the Rider Hub and we'll take another look.</p>"
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>{note_html}", ("Open Rider Hub", _url("/rider")))
    return title, html, _text(_greeting(name), "", blurb, f"Note: {note}" if note else "")


def direct_message(name: str | None, title: str, body: str, cta_path: str | None = None) -> Email:
    paragraphs = "".join(f"<p>{escape(line)}</p>" for line in body.splitlines() if line.strip())
    html = _layout(title, f"<p>{_greeting(name)}</p>{paragraphs}", ("Open Novo", _url(cta_path)) if cta_path else None)
    return f"{title} — Novo", html, _text(_greeting(name), "", body)


# ── Payouts ──────────────────────────────────────────────────────────────────

def settlement_sent(name: str | None, amount, path: str = "/merchant/earnings") -> Email:
    title = f"{_naira(amount)} is ready to withdraw"
    blurb = f"Novo has settled {_naira(amount)} to your payout account. You can withdraw it to your bank from your earnings page."
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>", ("View earnings", _url(path)))
    return title, html, _text(_greeting(name), "", blurb)


def payout_account_active(name: str | None) -> Email:
    title = "Your payout account is verified"
    blurb = "Bachs has verified your payout account. Settlements from Novo will now reach you, and you can withdraw to your bank anytime."
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{blurb}</p>")
    return title, html, _text(_greeting(name), "", blurb)


def withdrawal_finished(name: str | None, amount, ok: bool, reason: str | None) -> Email:
    if ok:
        title = f"{_naira(amount)} sent to your bank"
        blurb = f"Your withdrawal of {_naira(amount)} has been paid to your bank account."
    else:
        title = "Your withdrawal didn't go through"
        blurb = f"Your withdrawal of {_naira(amount)} failed{': ' + reason if reason else ''}. The money is still in your payout balance — check your bank details and try again."
    html = _layout(title, f"<p>{_greeting(name)}</p><p>{escape(blurb)}</p>")
    return title, html, _text(_greeting(name), "", blurb)
