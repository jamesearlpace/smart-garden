**Type:** UI correctness

The single-zone "Next Expected Watering" banner showed a bogus watering date for **manual-mode** zones (e.g. Garden drip, `auto_mode=false`): "Next Expected Watering: Friday Jun 5 ~4 AM — needs water". The engine never auto-waters a manual zone (`evaluate_zone` returns skip when `auto_mode=false`), so the banner was misleading.

**Root cause:** the banner has two implementations — `updateNextWateringBanner()` (which short-circuits manual/not-installed zones) and an **inline copy** added for bug #23 ("function call kept failing silently"). The inline copy never got the manual-mode guard.

**Fix (commit jamesearlpace/smart-garden@7026138):** added the same guard to the inline block — manual/not-installed zones now show "✋ Manual mode" / "⛔ Not installed" and skip the date projection.

**Verified live:** Garden (auto_mode=false) shows "Manual mode"; Front Yard A (auto_mode=true) still shows the predicted date.
