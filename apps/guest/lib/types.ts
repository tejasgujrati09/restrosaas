import type { components } from "api-client";

type S = components["schemas"];
export type QrSession = S["QrSessionOut"];
export type GuestMenu = S["GuestMenuOut"];
export type GuestItem = S["GuestItemOut"];
export type GuestModifierGroup = S["GuestModifierGroupOut"];
export type TabView = S["TabOut"];
export type Round = S["RoundOut"];
export type Line = S["LineOut"];
export type Quote = S["QuoteOut"];
export type Totals = S["TotalsOut"];
export type ServiceRequestType = S["ServiceRequestIn"]["type"];
export type GuestSessionInfo = S["GuestSessionOut"];
