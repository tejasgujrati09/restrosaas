from __future__ import annotations

from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, invalid
from app.audit import audit
from app.core.gstin import gstin_state_code, is_valid_gstin
from app.core.invoice import format_invoice_no, validate_invoice_prefix
from app.core.permissions import Capability, assert_can
from app.deps import OutletContext
from app.domains.menu.models import MenuItem
from app.domains.tenant.models import Outlet, Restaurant, TaxClass
from app.errors import ApiError
from app.idempotency import fingerprint, run_idempotent

router = APIRouter(prefix="/v1/outlets/{outlet_id}/settings", tags=["settings"])


class SettingsOut(BaseModel):
    legal_name: str
    brand_name: str
    gstin: str | None
    outlet_name: str
    address: str | None
    timezone: str
    state_code: str
    liquor_licensed: bool
    liquor_vat_rate_bp: int
    service_charge_bp: int
    prices_include_tax: bool
    ack_threshold_paise: int
    waiter_confirm_mode: bool
    liquor_approval_required: bool
    # Read-only here; managers change them on the Assign tables screen.
    auto_assign_unassigned_table_orders: bool
    auto_assignment_strategy: str
    invoice_prefix: str
    next_invoice_no: int
    next_invoice_preview: str
    ready_to_go_live: bool
    go_live_blockers: list[str]
    suspended: bool


class SettingsPatchIn(BaseModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, min_length=1, max_length=200)
    gstin: str | None = None
    outlet_name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    timezone: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^[0-9]{2}$")
    liquor_licensed: bool | None = None
    liquor_vat_rate_bp: int | None = Field(default=None, ge=0, le=10_000)
    service_charge_bp: int | None = Field(default=None, ge=0, le=10_000)
    prices_include_tax: bool | None = None
    ack_threshold_paise: int | None = Field(default=None, ge=0)
    waiter_confirm_mode: bool | None = None
    liquor_approval_required: bool | None = None
    invoice_prefix: str | None = None


_RESTAURANT_FIELDS = {"legal_name": "legal_name", "brand_name": "brand_name", "gstin": "gstin"}
_OUTLET_FIELDS = {
    "outlet_name": "name",
    "address": "address",
    "timezone": "timezone",
    "state_code": "state_code",
    "liquor_licensed": "liquor_licensed",
    "liquor_vat_rate_bp": "liquor_vat_rate_bp",
    "service_charge_bp": "service_charge_bp",
    "prices_include_tax": "prices_include_tax",
    "ack_threshold_paise": "ack_threshold_paise",
    "waiter_confirm_mode": "waiter_confirm_mode",
    "liquor_approval_required": "liquor_approval_required",
    "invoice_prefix": "invoice_prefix",
}


async def build_settings(ctx: OutletContext) -> SettingsOut:
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert restaurant is not None and outlet is not None
    tax_classes = await ctx.session.scalar(
        select(func.count()).select_from(TaxClass).where(TaxClass.outlet_id == outlet.id)
    )
    blockers = []
    if not tax_classes:
        blockers.append("Add at least one tax class.")
    return SettingsOut(
        legal_name=restaurant.legal_name,
        brand_name=restaurant.brand_name,
        gstin=restaurant.gstin,
        outlet_name=outlet.name,
        address=outlet.address,
        timezone=outlet.timezone,
        state_code=outlet.state_code,
        liquor_licensed=outlet.liquor_licensed,
        liquor_vat_rate_bp=outlet.liquor_vat_rate_bp,
        service_charge_bp=outlet.service_charge_bp,
        prices_include_tax=outlet.prices_include_tax,
        ack_threshold_paise=outlet.ack_threshold_paise,
        waiter_confirm_mode=outlet.waiter_confirm_mode,
        liquor_approval_required=outlet.liquor_approval_required,
        auto_assign_unassigned_table_orders=outlet.auto_assign_unassigned_table_orders,
        auto_assignment_strategy=outlet.auto_assignment_strategy,
        invoice_prefix=outlet.invoice_prefix,
        next_invoice_no=outlet.next_invoice_no,
        next_invoice_preview=format_invoice_no(outlet.invoice_prefix, outlet.next_invoice_no),
        ready_to_go_live=not blockers,
        go_live_blockers=blockers,
        suspended=restaurant.status == "suspended",
    )


@router.get("", responses=ERRORS)
async def get_settings(ctx: Ctx) -> SettingsOut:
    assert_can(ctx.actor, Capability.VIEW_OUTLET_SETTINGS, ctx.outlet_id)
    return await build_settings(ctx)


@router.patch("", responses=ERRORS)
async def update_settings(
    ctx: Ctx, key: IdempotencyKeyHeader, body: Annotated[SettingsPatchIn, Body()]
) -> SettingsOut:
    assert_can(ctx.actor, Capability.EDIT_OUTLET_SETTINGS, ctx.outlet_id)
    return await run_idempotent(
        ctx.session,
        ctx.restaurant_id,
        ctx.actor.user_id,
        key,
        fingerprint("PATCH", f"settings/{ctx.outlet_id}", body.model_dump(exclude_unset=True)),
        SettingsOut,
        lambda: _apply(ctx, body),
    )


async def _apply(ctx: OutletContext, body: SettingsPatchIn) -> SettingsOut:
    restaurant = await ctx.session.get(Restaurant, ctx.restaurant_id)
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert restaurant is not None and outlet is not None
    changes = body.model_dump(exclude_unset=True)
    before = {name: getattr(_owner(restaurant, outlet, name), _column(name)) for name in changes}

    if "gstin" in changes and changes["gstin"] is not None:
        # Optional for now: a blank value clears it. When given it must still be valid.
        changes["gstin"] = changes["gstin"].strip().upper() or None
        if changes["gstin"] is not None and not is_valid_gstin(changes["gstin"]):
            raise invalid("gstin", "That GSTIN is not valid. Check it and try again.")
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"] or "")
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise invalid("timezone", "Unknown timezone.") from exc
    if "invoice_prefix" in changes:
        try:
            validate_invoice_prefix(changes["invoice_prefix"] or "", outlet.next_invoice_no)
        except ValueError as exc:
            raise invalid("invoice_prefix", str(exc)) from exc
    if (
        "prices_include_tax" in changes
        and changes["prices_include_tax"] != outlet.prices_include_tax
    ):
        items = await ctx.session.scalar(
            select(func.count()).select_from(MenuItem).where(MenuItem.outlet_id == outlet.id)
        )
        if items:
            raise ApiError(
                409,
                "prices_mode_locked",
                "Prices can't switch between with-tax and plus-tax once the menu has items.",
            )

    new_gstin = changes.get("gstin", restaurant.gstin)
    new_state = changes.get("state_code", outlet.state_code)
    if new_gstin and gstin_state_code(new_gstin) != new_state:
        raise invalid("gstin", "The first two digits of the GSTIN must match the state code.")

    for name, value in changes.items():
        setattr(_owner(restaurant, outlet, name), _column(name), value)
    await ctx.session.flush()

    after = {name: getattr(_owner(restaurant, outlet, name), _column(name)) for name in changes}
    if changes:
        audit(ctx, "outlet.settings_updated", "outlet", outlet.id, before, after)
    if "invoice_prefix" in changes and before["invoice_prefix"] != after["invoice_prefix"]:
        audit(
            ctx,
            "outlet.invoice_prefix_changed",
            "outlet",
            outlet.id,
            {"invoice_prefix": before["invoice_prefix"]},
            {"invoice_prefix": after["invoice_prefix"], "next_invoice_no": outlet.next_invoice_no},
        )
    return await build_settings(ctx)


def _owner(restaurant: Restaurant, outlet: Outlet, name: str) -> Any:
    return restaurant if name in _RESTAURANT_FIELDS else outlet


def _column(name: str) -> str:
    return _RESTAURANT_FIELDS.get(name) or _OUTLET_FIELDS[name]
