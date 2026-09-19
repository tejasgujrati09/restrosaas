"""Creates (or reuses) a demo restaurant so the running stack can be tried straight away.

    uv run python scripts/seed_demo.py <api url> <staff app url>

Development only: it relies on the fixed sign-in code the dev script sets. Safe to run
again; it reuses the demo owner's restaurant and only adds what is missing. Writes the
links and sign-in details to .run/demo.txt for `scripts/dev.sh status`.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import httpx

API = sys.argv[1].rstrip("/")
STAFF = sys.argv[2].rstrip("/")
PHONE = "+918888800001"  # not the +91999 prefix the automated tests clean up
CODE = "123456"
GSTIN = "29AAPFU0939F1ZR"  # valid checksum for state 29 (Karnataka)
OUT = Path(__file__).resolve().parent.parent / ".run" / "demo.txt"

client = httpx.Client(base_url=API, timeout=30)


def ok(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        sys.exit(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json() if response.content else {}


def claims(token: str) -> dict:
    """The role claims in the access token (read only to find our outlet id)."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def sign_in() -> tuple[str, str]:
    """Returns (access token, outlet id), signing the demo owner up on first run."""
    client.post("/v1/auth/otp/request", json={"phone": PHONE})
    login = client.post("/v1/auth/otp/verify", json={"phone": PHONE, "code": CODE})
    if login.status_code == 200:
        token = login.json()["access_token"]
        roles = claims(token).get("roles", [])
        if roles:
            return token, roles[0]["outlet_id"]
    client.post("/v1/signup/otp", json={"phone": PHONE})
    body = ok(
        client.post(
            "/v1/signup",
            json={
                "phone": PHONE,
                "code": CODE,
                "owner_name": "Demo Owner",
                "legal_name": "Demo Hospitality Pvt Ltd",
                "brand_name": "Demo Bar & Kitchen",
                "outlet_name": "Indiranagar",
                "state_code": "29",
            },
        )
    )
    return body["access_token"], body["outlet_id"]


token, outlet = sign_in()
auth = {"Authorization": f"Bearer {token}"}
base = f"/v1/outlets/{outlet}"


def get(path: str) -> object:
    return ok(client.get(f"{base}{path}", headers=auth))


def send(method: str, path: str, body: dict) -> dict:
    return ok(client.request(method, f"{base}{path}", json=body, headers=auth))


ok(client.patch(f"{base}/settings", json={"gstin": GSTIN, "service_charge_bp": 1000, "liquor_licensed": True, "liquor_vat_rate_bp": 2000}, headers=auth))

menu = get("/menu")
if not menu["categories"]:
    food = send("POST", "/tax-classes", {"name": "Food 5%", "gst_rate_bp": 500})
    liquor = send("POST", "/tax-classes", {"name": "Liquor VAT", "gst_rate_bp": 0, "liquor_vat": True})
    spice = send(
        "POST",
        "/modifier-groups",
        {"name": "Spice level", "min_select": 1, "max_select": 1, "modifiers": [{"name": "Mild"}, {"name": "Medium"}, {"name": "Hot", "price_delta_paise": 1000}]},
    )
    starters = send("POST", "/categories", {"name": "Starters"})
    mains = send("POST", "/categories", {"name": "Mains"})
    drinks = send("POST", "/categories", {"name": "Drinks"})
    items = [
        (starters, "Paneer Tikka", 32000, food, True, False, [spice["id"]]),
        (starters, "Chicken 65", 34000, food, False, False, [spice["id"]]),
        (starters, "Spring Roll", 15000, food, True, False, []),
        (mains, "Butter Chicken", 42000, food, False, False, []),
        (mains, "Dal Makhani", 29000, food, True, False, []),
        (drinks, "Craft Beer (pint)", 30000, liquor, True, True, []),
        (drinks, "Fresh Lime Soda", 9000, food, True, False, []),
    ]
    made = {}
    for category, name, price, tax, veg, is_liquor, groups in items:
        made[name] = send(
            "POST",
            "/items",
            {"category_id": category["id"], "name": name, "base_price_paise": price, "tax_class_id": tax["id"], "veg_flag": veg, "is_liquor": is_liquor, "modifier_group_ids": groups},
        )
    send(
        "POST",
        "/price-rules",
        {
            "name": "Happy hour",
            "scope": "item",
            "target_id": made["Craft Beer (pint)"]["id"],
            "rule_type": "fixed",
            "value": 20000,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "start_time": "16:00:00",
            "end_time": "20:00:00",
        },
    )

tables = get("/tables")
if not tables:
    send("POST", "/tables/bulk", {"zone": "floor", "labels": ["T1", "T2", "T3", "T4"], "seats": 4})
    tables = get("/tables")

def staff_member(phone: str, role: str, name: str) -> None:
    """Invites and accepts a staff member, unless they already work here."""
    client.post("/v1/auth/otp/request", json={"phone": phone})
    login = client.post("/v1/auth/otp/verify", json={"phone": phone, "code": CODE})
    if login.status_code == 200 and claims(login.json()["access_token"]).get("roles"):
        return
    invite = send("POST", "/invites", {"phone": phone, "role": role})
    token = invite["link"].rsplit("/", 1)[1]
    ok(client.post("/v1/invites/otp", json={"token": token}))
    ok(client.post("/v1/invites/accept", json={"token": token, "code": CODE, "name": name}))


WAITER, KITCHEN = "+918888800002", "+918888800003"
staff_member(WAITER, "waiter", "Ravi (waiter)")
staff_member(KITCHEN, "kitchen", "Kitchen")
client.post("/v1/auth/otp/request", json={"phone": WAITER})
waiter_id = claims(ok(client.post("/v1/auth/otp/verify", json={"phone": WAITER, "code": CODE}))["access_token"])["sub"]
by_label = {row["label"]: row["table_id"] for row in get("/table-assignments")}
for label in ("T1", "T2"):
    send("PUT", f"/tables/{by_label[label]}/assignees", {"user_ids": [waiter_id]})

lines = [
    "Demo venue (created by scripts/seed_demo.py)",
    f"  Owner sign-in    {STAFF}/login   phone 8888800001, code {CODE}   (also acts as manager)",
    f"  Waiter sign-in   same page, phone 8888800002: sees only tables T1 and T2",
    f"  Kitchen sign-in  same page, phone 8888800003: the ticket queue",
    "  Guest links (open on a phone-sized window):",
    *[f"    Table {t['label']:<3} {t['qr_url']}" for t in tables],
    "  Happy hour: Craft Beer is Rs 200 between 4 PM and 8 PM, otherwise Rs 300.",
]
OUT.parent.mkdir(exist_ok=True)
OUT.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
