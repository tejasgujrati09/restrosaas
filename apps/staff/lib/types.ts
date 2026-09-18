import type { components } from "api-client";

type S = components["schemas"];
export type Settings = S["SettingsOut"];
export type Menu = S["MenuOut"];
export type MenuCategory = S["MenuCategoryOut"];
export type Item = S["ItemOut"];
export type ItemIn = S["ItemIn"];
export type TaxClass = S["TaxClassOut"];
export type Station = S["StationOut"];
export type ModifierGroup = S["ModifierGroupOut"];
export type Table = S["TableOut"];
export type Staff = S["StaffOut"];
export type Invite = S["InviteOut"];
export type PriceRule = S["PriceRuleOut"];
export type PriceRuleIn = S["PriceRuleIn"];
export type ImportPreview = S["ImportPreviewOut"];
export type Role = S["Role"];
