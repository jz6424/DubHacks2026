# Crash Replay: go/no-go spike (2026-10-17)

Scripts: `run_track.py` (native vs per-frame), `analyze_track.py` (association + eyeball sheets), `run_events.py`
(OCR, signal, first contact), `geometry.py` (lane-line homography, ego speed, actor speeds). Raw model outputs are
cached in `out/` (gitignored; regenerate by re-running).

## Clips (all public domain, Wikimedia Commons)
| id | file | length | why |
|---|---|---|---|
| tesla_kia | [INSANE Car Crash caught on TeslaCam- Kia Soul flying through air!.webm](https://commons.wikimedia.org/wiki/File:INSANE_Car_Crash_caught_on_TeslaCam-_Kia_Soul_flying_through_air!.webm) | 29 s, 720p | US freeway, daytime, crisp lane dashes |
| sb400 | [400 SB Crash.webm](https://commons.wikimedia.org/wiki/File:400_SB_Crash.webm) | 17.6 s, 1080p | Garmin overlay (time, GPS, speed), snow, multi-vehicle |
| royalmail_cyclist | [Royal Mail van - Near collision with a cyclist.webm](https://commons.wikimedia.org/wiki/File:Royal_Mail_van_-_Near_collision_with_a_cyclist.webm) | 51 s | only used for a traffic-signal probe |

Rejected: `van_lanechange` (purple privacy masks over vehicles), the LAPD Code-3 clip (graphic, injured occupant).
No public-domain clip found with a clean signalized-intersection crash.

## Results
| test | result | verdict |
|---|---|---|
| (a) Native tracks (`detect` on 16-frame `video_frames` windows) | 2 objects/frame median vs ~8–10 visible; boxes drift onto empty road; truck and pickup dropped (tesla). OK on sb400 trucks | ✗ don't rely |
| (a) Per-frame `detect` (effort `none`) + IoU/Hungarian | tight boxes, all key actors found incl. Kia mid-flip; pickup one ID 3–20 s; Kia ID breaks at the flip; truck splits in 2 | ✓ with re-ID / merge |
| (b) Overlay OCR, sb400, 18 frames | speed, time, lat **18/18 exact** | ✓ rely |
| (b) Signal state, 8 frames + 5 negatives | negatives 5/5 "none"; dark head reported "green, high conf." 3/3 ✗; red at 38 s ✓; 1 empty output | ✗ evidence only, human-confirm |
| (b) First contact (`expects="clip"`) | timing within ~0.5 s on both; **mechanism wrong** on tesla (says Kia hit pickup; it hit a loose wheel); sb400 says "white truck", is a white car | timing ✓ / description ✗ |
| (c) Geometry, tesla | camera h=1.37 m, f→52° HFOV (both plausible); ego ≈92–103 km/h from dash flow; Kia 104 km/h (p10–p90 97–107) at 7–25 m; pickup lateral +3.9 m (= one lane) | ✓ near/same-lane; ✗ >40 m and trucks |
| (c) Geometry, sb400 | lanes snow-covered, no homography; ego speed from OCR only | report "insufficient" |
| (d) Cost/latency | tesla per-frame detect: 116 calls, 106k in / 16k out ≈ $0.04, ~55 s wall at 3 concurrent; OCR ~2 s/frame; clip query 4 s (low) vs 49 s (high) | ✓ cheap; live path ~1–2 min |

## Constraints discovered
- Max **8192 completion tokens** per call (server rejects more); reasoning counts toward it.
- Context window reportedly 36,864 tokens; ~330 prompt tokens per 1280-px frame, so ~100 frames/call, not 256.
- Cloudflare 1015 rate limit at 8 concurrent requests; 3 concurrent + backoff is fine.
- Box coords are normalized 0–1000; track/clip times are rounded to 0.1 s (snap to nearest frame).
- `@perceive` functions must return composed nodes (`image(...) + text(...)`), not a list.
