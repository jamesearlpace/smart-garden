# Sprinkler Head Selection Plan

**Status:** Decision made — Hunter MP Rotators  
**Last Updated:** 2026-06-15

---

## ⏳ PLANNED — Head Removals Due to Low Pressure (2026-06-15)

**Not yet applied.** James is physically removing several sprinkler heads because there
isn't enough water pressure to feed all of them at once (low-flow supply, ~5.5–6.0 GPM).
Fewer heads per zone = more pressure/throw at each remaining head. This documents the
planned removal so it can eventually be reflected on the live map
(`sprinklers.savagepace.com` → `MAP_HEADS` in `server-prod/templates/index.html`) and
in the per-zone `est_gpm` config. **Do NOT edit the live map or config until the head
list below is confirmed with James.**

### Heads marked for removal — CONFIRMED 2026-06-15

Confirmed by James: **#2, #5, #10, #14, #18, #27** (6 heads). Dot numbers correspond to
`MAP_HEADS` index+1 (the same numbering shown on the digital map). One head removed from
each of six zones — none is a single-head zone, so **no zone is eliminated**.

| Head # | Zone (config id) | Heads on zone before → after | MAP_HEADS coords |
|--------|------------------|------------------------------|------------------|
| #2  | Zone 1 — Front Yard A         (id 0) | 4 → 3 | x:92.1, y:53.4 |
| #5  | Zone 2 — Front Yard B         (id 1) | 4 → 3 | x:62.4, y:65.2 |
| #10 | Zone 3 — Enclosed Backyard A  (id 2) | 4 → 3 | x:59.9, y:65.2 |
| #14 | Zone 4 — Enclosed Backyard B  (id 3) | 4 → 3 | x:37.2, y:77.1 |
| #18 | Zone 5 — Peonies              (id 4) | 4 → 3 | x:20.7, y:65.7 |
| #27 | Zone 7 — South Lawn A         (id 6) | 4 → 3 | x:18.6, y:43.3 |

### Why this helps
- Low-flow supply can't sustain pressure across all 27+ heads simultaneously.
- Dropping heads reduces per-zone GPM demand, raising residual pressure and throw at
  the heads that remain (matches the MP Rotator design constraint of keeping each zone
  under ~5.5 GPM total — see the design-constraint section below).

### When applying later (the "show it eventually" part)
1. ✅ Head list confirmed (#2, #5, #10, #14, #18, #27).
2. Remove those entries from `MAP_HEADS` in `server-prod/templates/index.html`
   (live mirror first per the mirror-layout workflow), OR mark them visually as
   "removed" (greyed/✕) rather than deleting, so the map records what was pulled.
3. Recompute each affected zone's `est_gpm` in `config.yaml` (fewer heads = lower GPM).
   Affected zones: 0, 1, 2, 3, 4, 6 (each drops one head; no zone eliminated).
4. Deploy + verify per the standard smart-garden mirror workflow; commit.

---

## Goal

Choose sprinkler heads that reliably cover 30-foot head-to-head spacing across 7 lawn zones (27 heads total), given a low-flow water supply. The system is controlled by a custom ESP32 smart irrigation controller (see `smart-garden-journey.md`).

---

## Site Constraints (Measured)

| Parameter | Value | How Measured |
|-----------|-------|-------------|
| **Flow at manifold** | 5.5–6.0 GPM | 5 gal bucket: 50–55 seconds |
| **Static pressure** | 60 PSI | Gauge at hose bibb, nothing running |
| **Head spacing** | 30 ft | Physically measured/planned in yard |
| **Heads per zone** | 3–4 | 7 zones: six with 4 heads, one (South) with 3 |
| **Total heads** | 27 | Front A(4) + Front B(4) + Backyard A(4) + Backyard B(4) + SE(4) + South(3) + SW(4) |
| **Full-circle (360°) positions** | 7 | Mid-field heads that need coverage in all directions |
| **Adjustable-arc positions** | 20 | Edge/corner heads (90°–210°) |

---

## The Problem

The original plan used **Rain Bird 42SA+ rotor heads** rated at 3 GPM each. With 4 heads per zone that's 12 GPM demand — more than double the 5.5–6.0 GPM supply. The system can't deliver enough water; pressure drops, heads don't throw far enough, and you get dry spots.

### Why not just use a smaller rotor nozzle?

Traditional rotors (42SA+, Rain Bird 5004, etc.) trade flow for distance. Shrinking the nozzle reduces GPM but also reduces throw:

| Rotor Nozzle | GPM | Throw | Fits 30 ft? | Fits 6 GPM budget (×4)? |
|-------------|-----|-------|-------------|------------------------|
| #3 (standard) | 3.0 | 33-36 ft | Yes | No (12 GPM) |
| #2 | 2.0 | 29-32 ft | Borderline | No (8 GPM) |
| #1.5 | 1.5 | 27-29 ft | Short | Barely (6 GPM, 0 margin) |
| #1 | 1.0 | 24-26 ft | No | Yes (4 GPM) |

There's no traditional rotor nozzle that gives both low flow AND 30-foot throw. The #1.5 is closest but runs at 100% capacity with zero margin — if someone turns on a faucet inside, pressure drops and heads fall short.

---

## Decision: Hunter MP Rotator Nozzles

MP Rotators use **multi-stream rotating technology** that delivers water slowly in multiple rotating streams. This lets them throw far on very little flow — exactly what a low-flow system needs.

### Selected Nozzles

| Nozzle | Arc | Radius | Qty | Position |
|--------|-----|--------|-----|----------|
| **Hunter MP3500-90** | 90–210° adjustable | 31–35 ft | 20 | Edges, corners |
| **Hunter MP3000-360** | 360° fixed | 22–30 ft | 7 | Mid-field, full circle |

**Note:** The MP3500 is only available in adjustable arc (90–210°). There is no MP3500-360.

### Verified Performance Data (from Hunter Catalog US, pages 42–44)

**MP3000-360 (full circle) — your 7 mid-field heads:**

| PSI | Radius | GPM | Precip (sq / tri) |
|-----|--------|-----|-------------------|
| 30 | 27 ft | 3.15 | 0.42 / 0.48 |
| 35 | 28 ft | 3.40 | 0.42 / 0.48 |
| **40** | **30 ft** | **3.64** | **0.39 / 0.45** |
| 45 | 30 ft | 3.86 | 0.41 / 0.48 |
| 50 | 30 ft | 4.07 | 0.44 / 0.50 |

**MP3500 (adjustable arc) — your 20 edge/corner heads:**

| PSI | Radius | GPM @ 90° | GPM @ 180° | GPM @ 210° |
|-----|--------|-----------|------------|------------|
| 30 | 34 ft | 1.13 | 2.24 | 2.84 |
| 35 | 34 ft | 1.21 | 2.65 | 3.08 |
| **40** | **35 ft** | **1.28** | **2.86** | **3.29** |
| 45 | 35 ft | 1.38 | 3.10 | 3.54 |
| 50 | 35 ft | 1.43 | 3.21 | 3.76 |

### Why These Work

**Flow budget depends on arc setting.** The GPM per MP3500 head varies dramatically with arc — a 90° corner head uses ~1.28 GPM while a 180° half-circle uses ~2.86 GPM at the recommended 40 PSI. This is critical for zone design.

**Worst case (4 heads, all 360° MP3000):**
- Not possible on a mixed zone (MP3500 doesn't come in 360°), but a pure MP3000 zone: 1 × 3.64 GPM = 3.64 for each 360° head. Max 1 full-circle head per zone keeps flow reasonable.

**Typical mixed zone @ 40 PSI (2 corner 90° + 1 half 180° + 1 full-circle 360°):**
- (2 × 1.28) + (1 × 2.86) + (1 × 3.64) = 9.06 GPM — **exceeds supply!**

**This means zones must be designed so total GPM stays under 5.5 GPM.** Practical combinations that work:
- 4 × MP3500 at 90° = 5.12 GPM ✓
- 3 × MP3500 at 90° + 1 × MP3000-360 = 3.84 + 3.64 = 7.48 GPM ✗ — too high at 40 PSI
- 3 × MP3500 at 90° + 1 × MP3000-360 at **30 PSI** = 3.39 + 3.15 = 6.54 GPM — still tight

**⚠️ IMPORTANT DESIGN CONSTRAINT:** Zones with MP3000-360 heads cannot have many other heads on the same zone, because the 360° nozzle alone uses 3.15–3.64 GPM. Options:
1. **Limit zones with 360° heads to 2 total heads** (1 full-circle + 1 corner)
2. **Put 360° heads on dedicated zones** with fewer heads
3. **Re-evaluate whether some positions can use MP3000-90 (adjustable arc) instead of 360°** — at 90° the MP3000 only uses 0.86 GPM at 40 PSI

**Throw distance @ 40 PSI (recommended):**
- MP3500 at 40 PSI throws 35 ft → use radius adjustment screw to dial back to 30 ft (up to 25% reduction per catalog)
- MP3000-360 at 40 PSI throws exactly 30 ft → right on target

**Uniformity:**
- All MP Rotator models share a matched precipitation rate (~0.4 in/hr), so you can mix models on the same zone and the watering is even
- ~70% distribution uniformity — better than traditional rotors (~60%)

### Pop-Up Bodies

| Body | Qty | Notes |
|------|-----|-------|
| **Hunter Pro-Spray PRS40 4" pop-up** | 27 | Pressure-regulated to 40 PSI |

**Why PRS40:** The Hunter catalog explicitly states "Optimal pressure for the MP Rotator Nozzle is 40 PSI" and recommends the PRS40 body. At 40 PSI:
- MP3000-360 throws exactly 30 ft (your spacing)
- MP3500 throws 35 ft (use radius screw to reduce to 30 ft)
- Precipitation rates are at their most uniform

A PRS30 body would under-throw (MP3000-360 only reaches 27 ft at 30 PSI). An unregulated body at ~50 PSI wastes water and over-throws on the MP3500.

---

## How Coverage Works

At 30-foot head-to-head spacing with 30-foot throw, each head's spray reaches the adjacent head. This is called **head-to-head coverage** — every point in the yard gets hit by at least 2 spray patterns overlapping, which is the standard for good uniformity.

```
  H ← 30 ft → H ← 30 ft → H
  |←── spray ──→|←── spray ──→|
         ↑ overlap zone ↑
       (hit by 2 heads)
```

The radius adjustment screw on each MP Rotator lets you fine-tune the throw after installation. Turn clockwise to reduce throw, counter-clockwise to increase.

---

## Impact on Irrigation Schedule (Config Changes)

Because MP Rotators apply water at 0.4 in/hr (vs. 1.5 in/hr for traditional rotors), zones need to run longer to deliver the same amount of water. But the water soaks in as fast as it's applied — no runoff, no need for cycle-soak.

| Config Field | Old (rotor) | New (MP Rotator) | Why |
|-------------|-------------|-----------------|-----|
| `est_gpm` | 3.0 | **Varies by zone — see note** | Depends on arc settings of heads on the zone |
| `precip_rate_iph` | 1.5 | 0.4 | MP Rotator matched rate (Hunter catalog) |
| `max_runtime_min` | 24 | 45 | Slower precip = longer runs for same depth |
| `cycle_soak` | true (8 on / 25 off × 3) | false | Not needed — 0.4 in/hr soaks naturally |

**est_gpm must be calculated per zone** based on actual arc settings. Example at 40 PSI:
- Zone with 4 × MP3500 at 90°: 4 × 1.28 = 5.12 GPM
- Zone with 3 × MP3500 at 90° + 1 × MP3500 at 180°: (3 × 1.28) + 2.86 = 6.70 GPM ← exceeds supply
- Zone with 2 × MP3500 at 90° + 1 × MP3000-360: (2 × 1.28) + 3.64 = 6.20 GPM ← exceeds supply

The config values in `server-config.yaml.tmp` will need to be updated once exact arc assignments per zone are finalized.

These changes are already applied in `server-config.yaml.tmp`.

---

## Shopping List (Sprinkler Heads Only)

| Item | Qty | Est. $/ea | Est. Total |
|------|-----|----------|------------|
| Hunter Pro-Spray PRS40 4" pop-up body (PROS-04-PRS40) | 30 | ~$6 | ~$180 |
| Hunter MP3500-90 nozzle (90–210°) | 23 | ~$6 | ~$138 |
| Hunter MP3000-360 nozzle (360°) | 10 | ~$6 | ~$60 |
| **Total** | | | **~$378** |

*Quantities include 3 spare bodies and 3 spare nozzles of each type.*

**Where to buy:** Home Depot (in-store), SprinklerWarehouse.com, Amazon

**What to do with the 42SA+ heads:** Return if possible, otherwise keep as spare hardware.

---

## Open Questions / Things to Verify

- [ ] **CRITICAL: Resolve the 360° flow budget problem.** Each MP3000-360 head uses 3.64 GPM at 40 PSI — that's 60-66% of total supply on a single head. Zones with 360° heads need careful design to stay under 5.5 GPM total. Options: (a) dedicate zones to fewer heads when 360° is present, (b) reduce some 360° positions to adjustable arc, (c) accept reduced pressure/throw on those zones.
- [ ] Confirm which specific 7 head positions truly need full-circle (360°) vs. could work with adjustable arc (90-210°) — each 360° converted to 90° saves ~2.4 GPM on that zone
- [ ] After installation: run each zone and measure actual throw — adjust radius screws as needed
- [ ] After installation: do a catch-cup test (tuna cans) to verify precipitation rate is actually ~0.4 in/hr across the zone
- [ ] Verify the Pro-Spray PRS40 body thread (½" FPT inlet) matches the funny pipe adapters already in the inventory
- [ ] Verify Duvall WA soil type — if heavy clay, may need to re-enable cycle-soak even at 0.4 in/hr on sloped areas

---

## Reference: Full Inventory

All other materials (pipe, fittings, valves, wire, drip zones, enclosure, sensors) are tracked in `install-inventory.csv`. Only the sprinkler head rows changed — everything else is the same.
