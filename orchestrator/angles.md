# QA Angles Catalog

The director rotates through these lenses (and invents new ones). Goal: vet the
smart-garden website from many directions, the way a relentless human reviewer would.

## Functional
- Click EVERY button, link, tab, and control on a page; confirm each does what it claims.
- Submit every form with valid input; confirm the result.
- Every navigation target resolves (no dead `#`, no 404, no wrong anchor).

## Data accuracy
- Cross-check every displayed number/label against the API/DB (curl the endpoint).
- Time/relative-date labels ("today", "5h ago", "next watering") are correct vs now.
- Aggregates/scores are computed from the right rows (no inflation by manual/empty rows).

## Performance
- Page load time; time-to-interactive; slow API calls; oversized payloads.
- Console warnings about slow queries; chart render jank; excessive polling.

## Responsive / mobile
- Every page at mobile width: no overflow, tap targets usable, nav works, nothing clipped.

## States
- Empty state, loading state, and error state for every data-driven panel.
- What happens when an API 500s / returns no rows / is slow.

## Consistency
- Same datum shown on two pages must agree (dashboard vs detail vs chart).
- Terminology, zone naming, units consistent across pages.

## Accessibility
- Semantic headings, alt text, focus order, contrast, keyboard operability.

## Robustness / edge cases
- Boundary inputs (huge ranges, zero rows, future dates, year switches).
- Rapid clicks, double-submits, back/forward navigation.

## Security surface (client-side only)
- Exposed secrets in JS/HTML, unsafe innerHTML, missing auth on a route.

## Root-cause analysis (branch)
- When ANYTHING fails or looks wrong: find WHY, then check if the SAME root cause
  affects other pages/endpoints. "Is this a broader issue?" is the default follow-up.
