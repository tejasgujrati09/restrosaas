/*
 * CSS-built product illustrations. Every venue name, table, dish, price, name and figure here is
 * EXAMPLE DATA for illustration only, and each mock is labelled as an example where it's shown.
 * They are decorative (aria-hidden); the surrounding copy carries the meaning. Labels and states
 * mirror the real staff and guest apps (e.g. "Yes, ours" / "Not ours", "QR order" / "Voice").
 */
import { formatInr, Icon } from "@restosaas/ui";

const inr = (rupees: number) => formatInr(Math.round(rupees * 100));

/** Small visible "Example" tag so no mock reads as real customer data. */
export function ExampleTag({ children = "Example" }: { children?: string }) {
  return <span className="badge example-tag">{children}</span>;
}

export function GuestMenuPhone() {
  return (
    <div className="phone" aria-hidden="true">
      <div className="phone-screen">
        <div className="g-head">
          <span className="venue">The Tipsy Tiger</span>
          <span className="table-pill">Table 12</span>
        </div>
        <p className="deal-line">Happy hour until 8:00 PM · 20% off cocktails</p>
        <div className="chips">
          <span className="chip on">Cocktails</span>
          <span className="chip">Starters</span>
          <span className="chip">Mains</span>
          <span className="chip">Beer</span>
        </div>
        <div className="item">
          <div className="grow">
            <span className="name">Whisky sour</span>
            <span className="desc">Bourbon, lemon, egg white</span>
          </div>
          <div className="price">
            <span className="was">{inr(450)}</span>
            <span className="money">{inr(360)}</span>
            <span className="deal">Happy hour</span>
          </div>
          <span className="add">
            <Icon name="plus" />
          </span>
        </div>
        <div className="item">
          <div className="grow">
            <span className="name">
              <span className="dot" />
              Paneer tikka
            </span>
            <span className="desc">Mint chutney, pickled onion</span>
          </div>
          <div className="price">
            <span className="money">{inr(320)}</span>
          </div>
          <span className="add">
            <Icon name="plus" />
          </span>
        </div>
        <div className="item">
          <div className="grow">
            <span className="name">
              <span className="dot nonveg" />
              Chicken 65
            </span>
            <span className="desc">Curry leaf, green chilli</span>
          </div>
          <div className="price">
            <span className="money">{inr(360)}</span>
          </div>
          <span className="add">
            <Icon name="plus" />
          </span>
        </div>
        <div className="item off">
          <div className="grow">
            <span className="name">
              <span className="dot" />
              Masala fries
            </span>
            <span className="desc">Sold out tonight</span>
          </div>
          <div className="price">
            <span className="badge">Sold out</span>
          </div>
        </div>
        <div className="cta-mock">
          <span>View cart · 2 items</span>
          <span className="money">{inr(680)}</span>
        </div>
        <div className="bar-mock">
          <span className="on">Menu</span>
          <span>My tab</span>
          <span>Call waiter</span>
        </div>
      </div>
    </div>
  );
}

function FloorTiles() {
  return (
    <>
      <div className="tiles">
        <div className="tile state-seated">
          <span className="tile-name">T1</span>
          <span className="t-sub">Seated</span>
        </div>
        <div className="tile state-order">
          <span className="tile-name">T4</span>
          <span className="t-sub">Order in progress</span>
        </div>
        <div className="tile state-bill">
          <span className="tile-name">T7</span>
          <span className="t-sub">Bill requested</span>
        </div>
        <div className="tile state-free">
          <span className="tile-name">T9</span>
          <span className="t-sub">Free</span>
        </div>
      </div>
      <ul className="legend">
        <li>
          <span className="swatch state-seated" />
          Seated
        </li>
        <li>
          <span className="swatch state-order" />
          Order in progress
        </li>
        <li>
          <span className="swatch state-bill" />
          Bill requested
        </li>
        <li>
          <span className="swatch state-free" />
          Free
        </li>
      </ul>
    </>
  );
}

export function FloorCard() {
  return (
    <div className="floor-card" data-theme="dark" aria-hidden="true">
      <div className="mock-head">
        <h3>My tables</h3>
        <span className="conn">Live</span>
      </div>
      <FloorTiles />
    </div>
  );
}

export function GuestTabMock() {
  return (
    <div className="mock" aria-hidden="true">
      <div className="mock-head">
        <h3>My tab</h3>
        <span className="table-pill">Table 12</span>
      </div>
      <div className="lines">
        <div className="line">
          <div className="l-main">
            <span className="l-name">2 × Paneer tikka</span>
            <span className="l-sub">You · 9:12 PM</span>
          </div>
          <span className="money">{inr(640)}</span>
        </div>
        <div className="line">
          <div className="l-main">
            <span className="l-name">1 × Whisky sour</span>
            <span className="l-sub">
              Someone at your table · 9:14 PM <span className="deal">Happy hour</span>
            </span>
          </div>
          <span className="money">{inr(360)}</span>
        </div>
        <div className="line pending">
          <div className="l-main">
            <span className="l-name">1 × Chicken 65</span>
            <span className="l-sub">Ravi (waiter) · 9:31 PM</span>
            <span className="l-sub">Your waiter added this. Is it yours?</span>
            <div className="ack-row">
              <span className="btn">Yes, ours</span>
              <span className="btn secondary">Not ours</span>
            </div>
          </div>
          <span className="money">{inr(360)}</span>
        </div>
      </div>
      <dl className="totals">
        <div className="grand">
          <dt>Running total</dt>
          <dd className="money">{inr(1360)}</dd>
        </div>
      </dl>
      <div className="cta-mock">
        <span>Request the bill</span>
        <span className="money">{inr(1360)}</span>
      </div>
    </div>
  );
}

export function WaiterFloorMock() {
  return (
    <div className="mock" data-theme="dark" aria-hidden="true">
      <div className="mock-head">
        <h3>My tables</h3>
        <span className="conn">Live</span>
      </div>
      <FloorTiles />
      <div className="reqs">
        <div className="req">
          <Icon name="bell" />
          <div className="grow">
            <strong>Table 4 · Water</strong>
            <span className="r-sub">Since 9:40 PM</span>
          </div>
          <span className="btn secondary">Done</span>
        </div>
        <div className="req">
          <Icon name="bell" />
          <div className="grow">
            <strong>Table 7 · Bill</strong>
            <span className="r-sub">Since 9:42 PM</span>
          </div>
          <span className="btn">Done</span>
        </div>
      </div>
    </div>
  );
}

export function KitchenTicketsMock() {
  return (
    <div className="mock" data-theme="dark" aria-hidden="true">
      <div className="mock-head">
        <h3>Kitchen and bar</h3>
        <span className="badge">Station: Kitchen</span>
      </div>
      <div className="tickets">
        <div className="ticket">
          <div className="t-head">
            <h4>Table 4</h4>
            <span className="badge">3 min</span>
          </div>
          <p className="item-line">2 × Paneer tikka</p>
          <p className="item-line">1 × Chicken 65</p>
          <p className="t-mod">Less spicy</p>
          <span className="btn">Start</span>
        </div>
        <div className="ticket aged">
          <div className="t-head">
            <h4>Table 9</h4>
            <span className="badge danger">17 min</span>
          </div>
          <p className="item-line">1 × Butter chicken</p>
          <p className="item-line">3 × Garlic naan</p>
          <span className="btn">Ready</span>
        </div>
      </div>
    </div>
  );
}

export function OrdersMock() {
  const rows = [
    { where: "Phone order · waiting for a manager", items: "2 × Veg biryani, 1 × Raita", source: "Voice", status: "New", tone: "warn", value: 700 },
    { where: "Table 4", items: "2 × Paneer tikka, 1 × Chicken 65", source: "QR order", status: "New", tone: "warn", value: 1000 },
    { where: "Table 7", items: "3 × Garlic naan, 1 × Dal makhani", source: "Waiter", status: "Preparing", tone: "info", value: 640 },
  ];
  return (
    <div className="mock" aria-hidden="true">
      <div className="mock-head">
        <h3>Orders</h3>
        <span className="conn">Live</span>
      </div>
      <div className="seg-mock">
        <span className="on">New 2</span>
        <span>In progress 1</span>
        <span>Ready</span>
        <span>Completed</span>
        <span>Cancelled</span>
      </div>
      <div className="lines">
        {rows.map((r) => (
          <div className="line" key={r.where}>
            <div className="l-main">
              <span className="l-name">{r.where}</span>
              <span className="l-sub">{r.items}</span>
              <span className="l-sub">
                <span className="badge">{r.source}</span>
                <span className={`badge ${r.tone}`}>{r.status}</span>
              </span>
            </div>
            <span className="money">{inr(r.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AnalyticsMock() {
  return (
    <div className="mock" aria-hidden="true">
      <div className="mock-head">
        <h3>Analytics · Overview</h3>
        <span className="badge">Last 7 days</span>
      </div>
      <div className="kpis">
        <div>
          <span className="k-label">Rounds</span>
          <span className="k-val num">412</span>
        </div>
        <div>
          <span className="k-label">Order value</span>
          <span className="k-val money">{inr(598640)}</span>
        </div>
        <div>
          <span className="k-label">Average order value</span>
          <span className="k-val money">{inr(1453)}</span>
        </div>
        <div>
          <span className="k-label">Average prep time</span>
          <span className="k-val num">14 min</span>
        </div>
      </div>
      <div className="bars" aria-hidden="true">
        {[42, 55, 38, 61, 70, 92, 84].map((h, i) => (
          <span key={i} style={{ height: `${h}%` }} />
        ))}
      </div>
      <p className="note">Order value, not revenue: there is no billing behind these numbers. Export any panel to CSV.</p>
    </div>
  );
}
