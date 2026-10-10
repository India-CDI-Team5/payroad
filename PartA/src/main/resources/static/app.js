"use strict";

/*
 * Bargaining demo (card A5): one page, two roles. REST for create / sync / cancel / presence / market,
 * STOMP over native WebSocket (/ws) for commands and deal events (api-spec §4, §5).
 * The server is the only judge of the rules: the client never blocks a command, it only warns.
 */

const TIME_VALUE = 2.0;                 // ₹ per minute of pickup ETA, "Recommended" sort (api-spec §6.3)
const HEARTBEAT_MS = 20000;
const MARKET_POLL_MS = 3000;
const PURGE_AFTER_SEC = 300;            // a matched driver is free again at createdAt + 300 s (R10)
const CENTER = [12.9716, 77.5946];
const DEFAULT_IDS = { RIDER: "R001", DRIVER: "DR001" };
const PRESETS = [
    { name: "MG Road", lat: 12.9756, lng: 77.6066 },
    { name: "Koramangala", lat: 12.9352, lng: 77.6245 },
    { name: "Whitefield", lat: 12.9698, lng: 77.7500 },
    { name: "Indiranagar", lat: 12.9784, lng: 77.6408 },
    { name: "Airport", lat: 13.1986, lng: 77.7066 },
];

const $ = (id) => document.getElementById(id);

const state = {
    role: "RIDER",
    origin: null,
    dest: null,
    driverPos: null,
    online: false,
    deal: null,              // the deal on screen: GET /api/deals snapshot, kept current by events
    match: null,             // last deal.matched event for that deal
    endReason: null,
    sort: "price",
    sub: null,
    marketRows: {},          // dealId -> /api/market summary, for the driver's straight-line fallback
    timers: { heartbeat: null, market: null },
};

// ---------- map ----------

const map = L.map("map").setView(CENTER, 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const layers = { origin: null, dest: null, route: null, driver: null };

function point(lat, lng, color, label) {
    return L.circleMarker([lat, lng], { radius: 8, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 })
        .bindTooltip(label)
        .addTo(map);
}

function clearLayer(name) {
    if (layers[name]) {
        map.removeLayer(layers[name]);
        layers[name] = null;
    }
}

function drawOD(origin, dest) {
    clearLayer("origin");
    clearLayer("dest");
    if (origin) layers.origin = point(origin.lat, origin.lng, "#1a7f37", "Origin");
    if (dest) layers.dest = point(dest.lat, dest.lng, "#cf222e", "Destination");
}

/** Google's encoded polyline algorithm, precision 5. */
function decodePolyline(str) {
    const out = [];
    let index = 0, lat = 0, lng = 0;
    while (index < str.length) {
        for (const axis of [0, 1]) {
            let result = 0, shift = 0, byte;
            do {
                byte = str.charCodeAt(index++) - 63;
                result |= (byte & 0x1f) << shift;
                shift += 5;
            } while (byte >= 0x20);
            const delta = result & 1 ? ~(result >> 1) : result >> 1;
            if (axis === 0) lat += delta; else lng += delta;
        }
        out.push([lat / 1e5, lng / 1e5]);
    }
    return out;
}

function drawRoute(polyline, origin, dest) {
    clearLayer("route");
    let pts = polyline ? decodePolyline(polyline) : [];
    if (pts.length < 2 && origin && dest) pts = [[origin.lat, origin.lng], [dest.lat, dest.lng]];
    if (pts.length < 2) return;
    layers.route = L.polyline(pts, { color: "#1f6feb", weight: 5, opacity: 0.8 }).addTo(map);
    if (!origin || !dest) drawOD({ lat: pts[0][0], lng: pts[0][1] }, { lat: pts[pts.length - 1][0], lng: pts[pts.length - 1][1] });
    map.fitBounds(layers.route.getBounds(), { padding: [30, 30] });
}

map.on("click", (e) => {
    const p = { lat: e.latlng.lat, lng: e.latlng.lng };
    if (state.role === "DRIVER") {
        state.driverPos = p;
        clearLayer("driver");
        layers.driver = point(p.lat, p.lng, "#8250df", "Me");
        renderDriverPos();
        return;
    }
    if (state.deal && isActive(state.deal)) return;          // the route is fixed while a deal is open
    if (!state.origin || state.dest) {
        state.origin = p;
        state.dest = null;
    } else {
        state.dest = p;
    }
    $("preset-origin").value = "";
    $("preset-dest").value = "";
    clearLayer("route");
    drawOD(state.origin, state.dest);
    renderOD();
});

// ---------- helpers ----------

function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function money(v) {
    return v == null ? "–" : "₹" + Number(v).toFixed(2);
}

function num(v, digits = 2) {
    return v == null ? "–" : Number(v).toFixed(digits);
}

function secondsLeft(iso) {
    if (!iso) return null;
    return Math.max(0, Math.round((Date.parse(iso) - Date.now()) / 1000));
}

function clock(ms) {
    return new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
}

function actorId() {
    return $("actor-id").value.trim();
}

function isActive(deal) {
    return deal.status === "OPEN" || deal.status === "NEGOTIATING";
}

function toast(code, message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.innerHTML = `<b>${esc(code)}</b>${esc(message)}`;
    $("toasts").appendChild(el);
    setTimeout(() => el.remove(), 6000);
}

async function api(method, url, body) {
    try {
        const res = await fetch(url, {
            method,
            headers: body ? { "Content-Type": "application/json" } : {},
            body: body ? JSON.stringify(body) : undefined,
        });
        let data = null;
        try { data = await res.json(); } catch (_) { /* empty body */ }
        return { ok: res.ok, status: res.status, data };
    } catch (e) {
        toast("NETWORK_ERROR", `${method} ${url}: ${e.message}`);
        return { ok: false, status: 0, data: null };
    }
}

function restError(res, what) {
    const d = res.data || {};
    toast(d.code || `HTTP_${res.status}`, d.message || `${what} failed`);
}

// ---------- STOMP ----------

const brokerURL = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
const stomp = new StompJs.Client({ brokerURL, reconnectDelay: 2000, heartbeatIncoming: 10000, heartbeatOutgoing: 10000 });

stomp.onConnect = () => {
    setConnected(true);
    stomp.subscribe("/user/queue/errors", (m) => onCommandError(JSON.parse(m.body)));
    state.sub = null;                                   // subscriptions do not survive a reconnect
    if (state.deal) {
        subscribeDeal(state.deal.dealId);
        resync();
    }
};
stomp.onWebSocketClose = () => setConnected(false);
stomp.onStompError = (frame) => toast("STOMP_ERROR", frame.headers.message || "broker error");
stomp.activate();

function setConnected(on) {
    const el = $("conn");
    el.textContent = on ? "Connected" : "Disconnected";
    el.className = "conn " + (on ? "on" : "off");
}

function subscribeDeal(dealId) {
    if (state.sub) {
        try { state.sub.unsubscribe(); } catch (_) { /* connection already gone */ }
        state.sub = null;
    }
    if (stomp.connected) state.sub = stomp.subscribe(`/topic/deal/${dealId}`, (m) => onDealEvent(JSON.parse(m.body)));
}

function unsubscribeDeal() {
    if (state.sub) {
        try { state.sub.unsubscribe(); } catch (_) { /* connection already gone */ }
        state.sub = null;
    }
}

/** Every command carries the last version this page saw (api-spec §5.6). */
function send(path, body) {
    if (!state.deal) return;
    if (!stomp.connected) {
        toast("DISCONNECTED", "Not connected to the server; the command was not sent");
        return;
    }
    stomp.publish({
        destination: `/app/deal/${state.deal.dealId}/${path}`,
        body: JSON.stringify({ ...body, version: state.deal.version }),
    });
}

function onCommandError(err) {
    toast(err.code, err.message);
    if (err.code === "VERSION_CONFLICT" && state.deal && err.dealId === state.deal.dealId) resync();
}

async function resync() {
    if (!state.deal) return;
    const res = await api("GET", `/api/deals/${encodeURIComponent(state.deal.dealId)}`);
    if (res.ok && state.deal && res.data.dealId === state.deal.dealId) {
        state.deal = res.data;
        render();
    }
}

/** Apply one /topic/deal event. Stale ones are ignored; a gap in versions means a missed event, so resync. */
function onDealEvent(ev) {
    const d = state.deal;
    if (!d || ev.dealId !== d.dealId || ev.version <= d.version) return;
    if (ev.version > d.version + 1) {
        resync();
        return;
    }
    switch (ev.event) {
        case "bid.placed":
        case "bid.updated":
            d.bids = d.bids.filter((b) => b.driverId !== ev.bid.driverId).concat([ev.bid]);
            d.lowestBidPrice = ev.lowestBidPrice;
            d.bidderCount = ev.bidderCount;
            d.pendingSide = ev.pendingSide;
            d.round = ev.round;
            d.status = "NEGOTIATING";
            break;
        case "bid.withdrawn":
            d.bids = d.bids.filter((b) => b.bidId !== ev.bidId);
            d.lowestBidPrice = ev.lowestBidPrice;
            d.bidderCount = ev.bidderCount;
            d.round = ev.round;
            break;
        case "offer.posted":
            d.riderOffer = { price: ev.price, expiresAt: ev.expiresAt };
            d.pendingSide = ev.pendingSide;
            d.round = ev.round;
            d.status = "NEGOTIATING";
            break;
        case "offer.expired":
            d.riderOffer = null;
            d.pendingSide = ev.pendingSide;
            d.round = ev.round;
            break;
        case "deal.matched":
            d.status = "MATCHED";
            d.riderOffer = null;
            state.match = ev;
            break;
        case "deal.expired":
            d.status = ev.reason === "CANCELLED_BY_RIDER" ? "CANCELLED" : "EXPIRED";
            d.riderOffer = null;
            state.endReason = ev.reason;
            break;
        default:
            return;
    }
    d.version = ev.version;
    render();
}

// ---------- role ----------

function setRole(role) {
    if (role === state.role) return;
    const id = actorId();
    if (!id || id === DEFAULT_IDS[state.role]) $("actor-id").value = DEFAULT_IDS[role];
    state.role = role;
    leaveDeal();
    stopTimer("heartbeat");
    stopTimer("market");
    state.online = false;
    clearLayer("driver");
    clearLayer("origin");
    clearLayer("dest");
    clearLayer("route");
    $("role-rider").classList.toggle("active", role === "RIDER");
    $("role-driver").classList.toggle("active", role === "DRIVER");
    $("rider-panel").classList.toggle("hidden", role !== "RIDER");
    $("driver-panel").classList.toggle("hidden", role !== "DRIVER");
    if (role === "RIDER") drawOD(state.origin, state.dest);
    if (role === "DRIVER" && state.driverPos) layers.driver = point(state.driverPos.lat, state.driverPos.lng, "#8250df", "Me");
    $("driver-status").textContent = "";
    renderMarket([]);
    render();
}

function leaveDeal() {
    unsubscribeDeal();
    state.deal = null;
    state.match = null;
    state.endReason = null;
}

function stopTimer(name) {
    if (state.timers[name]) {
        clearInterval(state.timers[name]);
        state.timers[name] = null;
    }
}

$("role-rider").addEventListener("click", () => setRole("RIDER"));
$("role-driver").addEventListener("click", () => setRole("DRIVER"));

// ---------- rider ----------

function fillPresets() {
    for (const id of ["preset-origin", "preset-dest"]) {
        const sel = $(id);
        sel.innerHTML = `<option value="">Map / choose…</option>` +
            PRESETS.map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join("");
    }
}

function renderOD() {
    const f = (p) => (p ? `${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}` : "—");
    $("od-label").textContent = `From ${f(state.origin)}  →  To ${f(state.dest)}`;
}

$("preset-origin").addEventListener("change", (e) => {
    const p = PRESETS[e.target.value];
    if (!p) return;
    state.origin = { lat: p.lat, lng: p.lng };
    clearLayer("route");
    drawOD(state.origin, state.dest);
    renderOD();
});

$("preset-dest").addEventListener("change", (e) => {
    const p = PRESETS[e.target.value];
    if (!p) return;
    state.dest = { lat: p.lat, lng: p.lng };
    clearLayer("route");
    drawOD(state.origin, state.dest);
    renderOD();
});

$("create-deal").addEventListener("click", async () => {
    if (!state.origin || !state.dest) {
        toast("MISSING_ROUTE", "Choose an origin and a destination first");
        return;
    }
    const riderId = actorId();
    const res = await api("POST", "/api/deals", {
        riderId,
        origin: state.origin,
        dest: state.dest,
    });
    if (!res.ok) {
        restError(res, "Create deal");
        return;
    }
    leaveDeal();
    state.deal = res.data;
    subscribeDeal(state.deal.dealId);
    drawRoute(state.deal.routePolyline, state.origin, state.dest);
    stopTimer("heartbeat");
    state.timers.heartbeat = setInterval(() => {
        api("POST", "/api/presence/heartbeat", { actorId: riderId, actorType: "RIDER" });
    }, HEARTBEAT_MS);
    render();
});

document.querySelectorAll(".sort").forEach((btn) => btn.addEventListener("click", () => {
    state.sort = btn.dataset.sort;
    document.querySelectorAll(".sort").forEach((b) => b.classList.toggle("active", b === btn));
    render();
}));

function sortedBids(bids) {
    const key = {
        price: (b) => b.price,
        eta: (b) => b.pickupEtaMin,
        recommended: (b) => b.price + TIME_VALUE * b.pickupEtaMin,
    }[state.sort];
    return [...bids].sort((a, b) => key(a) - key(b) || a.price - b.price);
}

$("bid-rows").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-bid]");
    if (btn) send("accept-bid", { riderId: actorId(), bidId: btn.dataset.bid });
});

$("send-offer").addEventListener("click", () => {
    const price = parseFloat($("offer-price").value);
    if (!Number.isFinite(price)) {
        toast("INVALID_INPUT", "Enter an offer price");
        return;
    }
    send("offer", { riderId: actorId(), price });
});

$("cancel-deal").addEventListener("click", async () => {
    if (!state.deal) return;
    const url = `/api/deals/${encodeURIComponent(state.deal.dealId)}?riderId=${encodeURIComponent(actorId())}`;
    const res = await api("DELETE", url);
    if (!res.ok) restError(res, "Cancel deal");
});

function riderCard(d) {
    const offer = d.riderOffer
        ? `${money(d.riderOffer.price)} (${secondsLeft(d.riderOffer.expiresAt)} s left)`
        : "–";
    const rows = [
        ["Deal", d.dealId],
        ["Base price", money(d.basePrice)],
        ["Price band", `${money(d.priceBand.min)} – ${money(d.priceBand.max)}`],
        ["Distance", `${num(d.distanceKm)} km`],
        ["Duration", `${num(d.durationMin, 1)} min`],
        ["Avg rain", d.avgRainMm == null ? "–" : `${num(d.avgRainMm, 3)} mm/h`],
        ["Weather factor", d.weatherFactor == null ? "–" : num(d.weatherFactor, 3)],
        ["Price source", d.priceSource ?? "–"],
        ["Status", d.status],
        ["Round", d.round],
        ["Version", d.version],
        ["Expires in", isActive(d) ? `${secondsLeft(d.expiresAt)} s` : "–"],
        ["My offer", offer],
    ];
    return rows.map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${esc(v)}</span>`).join("");
}

function renderRider() {
    const d = state.deal;
    $("rider-deal").classList.toggle("hidden", !d);
    if (!d) return;
    $("rider-card").innerHTML = riderCard(d);
    const rows = sortedBids(d.bids);
    $("bid-rows").innerHTML = rows.length
        ? rows.map((b) => `<tr>
            <td>${money(b.price)}</td>
            <td>${num(b.pickupEtaMin, 1)} min</td>
            <td>${num(b.pickupDistanceKm)}</td>
            <td>${esc(b.driverId)}</td>
            <td><button class="small primary" type="button" data-bid="${esc(b.bidId)}">Accept</button></td>
          </tr>`).join("")
        : `<tr><td class="empty" colspan="5">No bids yet</td></tr>`;
}

// ---------- driver ----------

function renderDriverPos() {
    const p = state.driverPos;
    $("driver-pos").textContent = p ? `Me: ${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}` : "Me: not set";
}

$("go-online").addEventListener("click", async () => {
    if (!state.driverPos) {
        toast("MISSING_POSITION", "Click the map to set your position first");
        return;
    }
    const driverId = actorId();
    const res = await api("POST", "/api/presence/driver", {
        driverId,
        driverLat: state.driverPos.lat,
        driverLng: state.driverPos.lng,
    });
    if (!res.ok) {
        restError(res, "Go online");
        return;
    }
    state.online = true;
    $("driver-status").textContent = `${res.data.status} · presence until ${clock(Date.parse(res.data.expiresAt))}`;
    stopTimer("heartbeat");
    state.timers.heartbeat = setInterval(async () => {
        const p = state.driverPos;
        const hb = await api("POST", "/api/presence/heartbeat",
            { actorId: driverId, actorType: "DRIVER", driverLat: p.lat, driverLng: p.lng });
        if (hb.ok) $("driver-status").textContent = `Online · presence until ${clock(Date.parse(hb.data.expiresAt))}`;
    }, HEARTBEAT_MS);
    stopTimer("market");
    pollMarket();
    state.timers.market = setInterval(pollMarket, MARKET_POLL_MS);
});

async function pollMarket() {
    const p = state.driverPos;
    if (!p) return;
    const res = await api("GET", `/api/market?lat=${p.lat}&lng=${p.lng}&limit=30`);
    if (res.ok) renderMarket(res.data.deals);
}

function renderMarket(deals) {
    state.marketRows = Object.fromEntries(deals.map((d) => [d.dealId, d]));
    const selected = state.deal && state.deal.dealId;
    $("market-rows").innerHTML = deals.length
        ? deals.map((d) => `<tr data-deal="${esc(d.dealId)}" class="${d.dealId === selected ? "selected" : ""}">
            <td>${esc(d.dealId)}</td>
            <td>${money(d.basePrice)}</td>
            <td>${money(d.lowestBidPrice)}</td>
            <td>${money(d.riderOfferPrice)}</td>
            <td>${d.bidderCount}</td>
            <td>${secondsLeft(d.expiresAt)} s</td>
          </tr>`).join("")
        : `<tr><td class="empty" colspan="6">${state.online ? "No open deals within 10 km" : "Go online to see deals"}</td></tr>`;
}

$("market-rows").addEventListener("click", async (e) => {
    const tr = e.target.closest("tr[data-deal]");
    if (!tr) return;
    const res = await api("GET", `/api/deals/${encodeURIComponent(tr.dataset.deal)}`);
    if (!res.ok) {
        restError(res, "Open deal");
        return;
    }
    leaveDeal();
    state.deal = res.data;
    subscribeDeal(state.deal.dealId);
    const m = state.marketRows[state.deal.dealId];
    drawRoute(state.deal.routePolyline, m && m.originApprox, m && m.destApprox);
    if (state.driverPos) {
        clearLayer("driver");
        layers.driver = point(state.driverPos.lat, state.driverPos.lng, "#8250df", "Me");
    }
    $("bid-price").value = "";
    render();
});

function myBid(d) {
    return d.bids.find((b) => b.driverId === actorId()) || null;
}

$("bid-price").addEventListener("input", () => {
    const d = state.deal;
    const price = parseFloat($("bid-price").value);
    const mine = d && myBid(d);
    $("bid-warning").classList.toggle("hidden", !(mine && Number.isFinite(price) && price > mine.price));
});

$("send-bid").addEventListener("click", () => {
    const price = parseFloat($("bid-price").value);
    if (!Number.isFinite(price)) {
        toast("INVALID_INPUT", "Enter a bid price");
        return;
    }
    if (!state.driverPos) {
        toast("MISSING_POSITION", "Click the map to set your position first");
        return;
    }
    send("bid", { driverId: actorId(), price, driverLat: state.driverPos.lat, driverLng: state.driverPos.lng });
});

$("withdraw-bid").addEventListener("click", () => send("bid/withdraw", { driverId: actorId() }));
$("accept-offer").addEventListener("click", () => send("accept-offer", { driverId: actorId() }));

function driverCard(d) {
    const mine = myBid(d);
    const rows = [
        ["Deal", d.dealId],
        ["Base price", money(d.basePrice)],
        ["Price band", `${money(d.priceBand.min)} – ${money(d.priceBand.max)}`],
        ["Distance", `${num(d.distanceKm)} km`],
        ["Weather factor", d.weatherFactor == null ? "–" : num(d.weatherFactor, 3)],
        ["Status", d.status],
        ["Round", d.round],
        ["Version", d.version],
        ["Bidders", d.bidderCount],
        ["Lowest bid", money(d.lowestBidPrice)],
        ["My bid", mine ? `${money(mine.price)} (ETA ${num(mine.pickupEtaMin, 1)} min)` : "–"],
        ["Rider offer", d.riderOffer ? `${money(d.riderOffer.price)} (${secondsLeft(d.riderOffer.expiresAt)} s left)` : "–"],
        ["Expires in", isActive(d) ? `${secondsLeft(d.expiresAt)} s` : "–"],
    ];
    return rows.map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${esc(v)}</span>`).join("");
}

function renderDriver() {
    const d = state.deal;
    $("driver-deal").classList.toggle("hidden", !d);
    if (!d) return;
    $("driver-card").innerHTML = driverCard(d);
    $("accept-offer").classList.toggle("hidden", !d.riderOffer);
    const won = state.match && state.match.driverId === actorId();
    $("driver-matched").textContent = won
        ? `Matched — available again at ${clock(Date.parse(d.createdAt) + PURGE_AFTER_SEC * 1000)}`
        : "";
    document.querySelectorAll("#market-rows tr[data-deal]").forEach((tr) =>
        tr.classList.toggle("selected", tr.dataset.deal === d.dealId));
}

// ---------- banner and render ----------

function renderBanner() {
    const el = $("banner");
    const d = state.deal;
    if (d && d.status === "MATCHED" && state.match) {
        const m = state.match;
        el.className = "banner ok";
        el.textContent = `Matched with ${m.driverId} at ${money(m.finalPrice)} · ${m.matchPath} · chosen rank ${m.chosenRank}`;
    } else if (d && d.status === "MATCHED") {
        el.className = "banner ok";
        el.textContent = "Matched";
    } else if (d && (d.status === "EXPIRED" || d.status === "CANCELLED")) {
        el.className = "banner ended";
        el.textContent = `Deal ${d.status.toLowerCase()}${state.endReason ? ` (${state.endReason})` : ""}`;
    } else {
        el.className = "banner hidden";
        el.textContent = "";
    }
}

function render() {
    if (state.role === "RIDER") renderRider(); else renderDriver();
    renderBanner();
}

// The countdowns tick once a second. Only the cards are redrawn, so a click on a table button is never lost.
setInterval(() => {
    if (state.deal) {
        if (state.role === "RIDER") $("rider-card").innerHTML = riderCard(state.deal);
        else $("driver-card").innerHTML = driverCard(state.deal);
    }
    if (state.role === "DRIVER") {
        document.querySelectorAll("#market-rows tr[data-deal]").forEach((tr) => {
            const m = state.marketRows[tr.dataset.deal];
            if (m) tr.lastElementChild.textContent = `${secondsLeft(m.expiresAt)} s`;
        });
    }
}, 1000);

fillPresets();
renderOD();
renderDriverPos();
renderMarket([]);
render();
