from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.v1.common import (
    ERRORS,
    Ctx,
    IdempotencyKeyHeader,
    idempotent_write,
    invalid,
    not_found,
)
from app.audit import audit
from app.core.permissions import Capability, assert_can
from app.core.pricing import PricedItem, RuleScope, RuleType, effective_price
from app.deps import OutletContext
from app.domains.menu.models import MenuCategory, MenuItem, PriceRule
from app.domains.menu.orderable import rule_spec
from app.domains.tenant.models import Outlet

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["price-rules"])


class PriceRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: RuleScope
    target_id: UUID | None = None
    rule_type: RuleType
    # fixed: paise the item costs while the rule is active. percent_off: percent * 100.
    value: int = Field(ge=0)
    # 0 = Monday ... 6 = Sunday. A window that crosses midnight belongs to its start day.
    days_of_week: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    start_time: time
    end_time: time
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    active: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> PriceRuleIn:
        if (self.scope == RuleScope.ALL) != (self.target_id is None):
            raise ValueError(
                "target_id is required for item/category rules and not allowed for 'all'"
            )
        if self.rule_type == RuleType.PERCENT_OFF and self.value > 10_000:
            raise ValueError("percent_off value is percent * 100 and cannot exceed 10000")
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        if len(set(self.days_of_week)) != len(self.days_of_week):
            raise ValueError("days_of_week must not repeat a day")
        for moment in (self.valid_from, self.valid_to):
            if moment is not None and moment.tzinfo is None:
                raise ValueError("valid_from and valid_to must include a timezone")
        if self.valid_from and self.valid_to and self.valid_from >= self.valid_to:
            raise ValueError("valid_from must be before valid_to")
        return self


class PriceRuleOut(PriceRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class EffectivePriceOut(BaseModel):
    item_id: UUID
    unit_price_paise: int
    price_rule_id: UUID | None


async def _check_target(ctx: OutletContext, body: PriceRuleIn) -> None:
    if body.scope == RuleScope.ITEM:
        item = await ctx.session.get(MenuItem, body.target_id)
        exists = item is not None and item.outlet_id == ctx.outlet_id
    elif body.scope == RuleScope.CATEGORY:
        category = await ctx.session.get(MenuCategory, body.target_id)
        exists = category is not None and category.outlet_id == ctx.outlet_id
    else:
        return
    if not exists:
        raise invalid("target_id", f"That {body.scope.value} does not exist at this outlet.")


def _out(row: PriceRule) -> PriceRuleOut:
    return PriceRuleOut(
        id=row.id,
        name=row.name,
        scope=RuleScope(row.scope),
        target_id=row.target_id,
        rule_type=RuleType(row.rule_type),
        value=row.value,
        days_of_week=sorted(row.days_of_week),
        start_time=row.start_time,
        end_time=row.end_time,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        active=row.active,
    )


def _apply(row: PriceRule, body: PriceRuleIn) -> None:
    row.name, row.scope, row.target_id = body.name, body.scope.value, body.target_id
    row.rule_type, row.value = body.rule_type.value, body.value
    row.days_of_week = sorted(body.days_of_week)
    row.start_time, row.end_time = body.start_time, body.end_time
    row.valid_from, row.valid_to, row.active = body.valid_from, body.valid_to, body.active


@router.get("/price-rules", responses=ERRORS)
async def list_price_rules(ctx: Ctx) -> list[PriceRuleOut]:
    assert_can(ctx.actor, Capability.VIEW_MENU, ctx.outlet_id)
    rows = await ctx.session.scalars(
        select(PriceRule).where(PriceRule.outlet_id == ctx.outlet_id).order_by(PriceRule.name)
    )
    return [_out(r) for r in rows]


@router.post("/price-rules", status_code=201, responses=ERRORS)
async def create_price_rule(ctx: Ctx, key: IdempotencyKeyHeader, body: PriceRuleIn) -> PriceRuleOut:
    assert_can(ctx.actor, Capability.SET_PRICE_RULES, ctx.outlet_id)

    async def produce() -> PriceRuleOut:
        await _check_target(ctx, body)
        row = PriceRule(restaurant_id=ctx.restaurant_id, outlet_id=ctx.outlet_id)
        _apply(row, body)
        ctx.session.add(row)
        await ctx.session.flush()
        audit(ctx, "price_rule.created", "price_rule", row.id, None, body.model_dump(mode="json"))
        return _out(row)

    return await idempotent_write(ctx, key, "POST price-rules", body, PriceRuleOut, produce)


@router.put("/price-rules/{rule_id}", responses=ERRORS)
async def update_price_rule(
    rule_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: PriceRuleIn
) -> PriceRuleOut:
    assert_can(ctx.actor, Capability.SET_PRICE_RULES, ctx.outlet_id)

    async def produce() -> PriceRuleOut:
        row = await _owned_rule(ctx, rule_id)
        await _check_target(ctx, body)
        before = _out(row).model_dump(mode="json")
        _apply(row, body)
        await ctx.session.flush()
        audit(ctx, "price_rule.updated", "price_rule", row.id, before, body.model_dump(mode="json"))
        return _out(row)

    return await idempotent_write(
        ctx, key, f"PUT price-rules/{rule_id}", body, PriceRuleOut, produce
    )


@router.delete("/price-rules/{rule_id}", status_code=204, responses=ERRORS)
async def delete_price_rule(rule_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> None:
    assert_can(ctx.actor, Capability.SET_PRICE_RULES, ctx.outlet_id)

    async def produce() -> None:
        row = await _owned_rule(ctx, rule_id)
        audit(ctx, "price_rule.deleted", "price_rule", row.id, _out(row).model_dump(mode="json"))
        await ctx.session.delete(row)
        await ctx.session.flush()

    await idempotent_write(ctx, key, f"DELETE price-rules/{rule_id}", None, type(None), produce)


async def _owned_rule(ctx: OutletContext, rule_id: UUID) -> PriceRule:
    row = await ctx.session.get(PriceRule, rule_id)
    if row is None or row.outlet_id != ctx.outlet_id:
        raise not_found("Price rule")
    return row


@router.get("/menu/effective-prices", responses=ERRORS)
async def effective_prices(
    ctx: Ctx,
    at: Annotated[
        datetime | None, Query(description="Defaults to now; must include a timezone")
    ] = None,
) -> list[EffectivePriceOut]:
    """What each item costs at `at`, evaluated in the outlet's timezone."""
    assert_can(ctx.actor, Capability.VIEW_MENU, ctx.outlet_id)
    if at is not None and at.tzinfo is None:
        raise invalid("at", "Include a timezone, e.g. 2026-09-18T18:30:00+05:30.")
    instant = at or datetime.now(UTC)
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    rules = [
        rule_spec(r)
        for r in await ctx.session.scalars(
            select(PriceRule).where(PriceRule.outlet_id == ctx.outlet_id)
        )
    ]
    items = await ctx.session.scalars(
        select(MenuItem).where(MenuItem.outlet_id == ctx.outlet_id).order_by(MenuItem.name)
    )
    tz = ZoneInfo(outlet.timezone)
    result = []
    for item in items:
        price = effective_price(
            PricedItem(item.id, item.category_id, item.base_price_paise), rules, instant, tz
        )
        result.append(
            EffectivePriceOut(
                item_id=item.id,
                unit_price_paise=price.unit_price_paise,
                price_rule_id=price.price_rule_id,
            )
        )
    return result
