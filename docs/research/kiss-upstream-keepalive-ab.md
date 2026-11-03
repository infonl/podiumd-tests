# KISS behind the gateway without upstream keep-alive: A/B perf result

Measured 2026-10-27 and 2026-10-28 on ontw-dim1 (podiumd 4.10.0, KISS 3.2.0,
NGINX Gateway Fabric 2.6.x). The question: does an NGF
`UpstreamSettingsPolicy` with `keepAlive.connections: 0` on the KISS, ITA and
PABC upstreams cost measurable latency or throughput? The policy is a
mitigation for Kestrel CVE-2026-88092 and CVE-2026-70188.

## Conclusion

No measurable cost for KISS through the public gateway.

- Raw A against B2, the KISS p50 deltas are -2 to +1 ms. Every req/s, p50,
  p90 and p95 delta is within the round-to-round noise.
- No errors in either run: no 502, 504, connection resets or timeouts.
- Caveat: the control route (Open Zaak, keep-alive in both runs) became
  5.5 ms faster in B2, and KISS did not. Corrected for that shift, KISS p50 is
  3 to 6 ms worse with `keepAlive 0`. That is at the edge of the noise and
  assumes the network shift hit both hosts equally. Treat it as an upper bound:
  a few ms per request, against a client round trip of about 40 ms.

## Method

The scenarios are in `tests/perf/test_gateway_perf.py` (suite commit 8421cec):
anonymous read-only routes through the public gateway, one Locust run per
scenario, two rounds. Round 2 shows the noise between runs.

```bash
podiumd-tests run --env ontw-dim1 --tier perf --skip-doctor -- \
  tests/perf/test_gateway_perf.py --perf-users 10 --perf-duration 2m
```

10 users, 30 s warm-up, 120 s measured per scenario. The client was a laptop
outside the cluster, kept awake during the run.

| Run | Upstream keep-alive | Time (UTC) |
|---|---|---|
| B1 | 0 | 2026-10-27 16:00 to 16:27 |
| A | 16 (as before the change) | 2026-10-28 11:06 to 11:32 |
| B2 | 0 | 2026-10-28 11:39 to 12:04 |

Result directories, under `results/2026-10/`:

- B1: `20261027-160041_ontw-dim1_perf_26102716005068`
- A: `20261028-110650_ontw-dim1_perf_261028110645de`
- B2: `20261028-113903_ontw-dim1_perf_2610281139e1ce`

The result directories are not in git (`results/*/*/` is ignored); they are on
the machine that ran them. This page keeps the numbers.

## A against B2

Values are the mean of the two rounds; latencies in ms. The bracket gives the
noise, the difference between round 1 and round 2, for A / B2.

| Scenario | Metric | A (16) | B2 (0) | Delta | Noise A / B2 |
|---|---|---|---|---|---|
| kiss_healthz | req/s | 231.9 | 226.9 | -4.9 (-2%) | 24.0 / 4.1 |
| | p50 | 40.5 | 40.0 | -0.5 | 3 / 0 |
| | p95 | 60.0 | 65.0 | +5.0 | 14 / 2 |
| | p99 | 81.0 | 91.0 | +10 | 28 / 4 |
| kiss_healthcheck | req/s | 225.2 | 220.5 | -4.7 (-2%) | 14.5 / 1.2 |
| | p50 | 41.0 | 42.0 | +1.0 | 2 / 0 |
| | p95 | 65.0 | 67.0 | +2.0 | 6 / 0 |
| | p99 | 86.5 | 90.0 | +3.5 | 7 / 2 |
| kiss_challenge (302) | req/s | 205.6 | 213.6 | +8.0 (+4%) | 2.4 / 0.1 |
| | p50 | 45.0 | 43.0 | -2.0 | 0 / 0 |
| | p95 | 70.0 | 65.5 | -4.5 | 6 / 1 |
| | p99 | 93.0 | 86.0 | -7.0 | 4 / 2 |
| kiss_page (index and 8 assets) | req/s | 12.5 | 12.6 | 0 | 0.3 / 1.5 |
| | p50 | 775 | 760 | -15 | 10 / 60 |
| | p95 | 1045 | 1025 | -20 | 110 / 150 |
| | p99 | 1200 | 1550 | +350 | 200 / 900 |
| openzaak_root (control) | req/s | 171.8 | 191.9 | +20.1 (+12%) | 0.4 / 0.6 |
| | p50 | 52.5 | 47.0 | -5.5 | 1 / 0 |
| | p95 | 78.5 | 73.5 | -5.0 | 1 / 1 |
| | p99 | 120 | 120 | 0 | 0 / 0 |

The kiss_page p99 of B2 comes from one round (2000 against 1100 in the other):
an outlier inside the noise.

How to read it:

1. The control did not change between A and B2, yet it became 5 to 10% faster.
   The client network shifted in B2's favour, so raw deltas below about 5 ms
   mean nothing.
2. Against the control, KISS p50 is +3.5 ms (challenge), +5 ms (healthz) and
   +6.5 ms (healthcheck) worse with `keepAlive 0`. This fits one extra connect
   per request to Kestrel, but the size is close to the noise.
3. Throughput stays the same within 2 to 4%.

## B1 is not comparable

- The client froze three times during B1 (53 to 62 s each; the laptop slept)
  and had 10 ReadTimeouts in kiss_challenge round 1. Those failures are on
  the client side.
- The network was faster that day: control p50 27 ms, against 47 to 53 ms on
  2026-10-28.
- B1's KISS p50 was 13 to 17 ms against a control of 27 ms. On a faster network,
  too, KISS with `keepAlive 0` shows no large cost.

## Repeating it

Run the command above once before and once after a gateway change, with the
same `--perf-users` and `--perf-duration`, from the same client, close in time.
Keep the laptop awake (`caffeinate -i` on macOS) and check Locust's
`*_stats_history.csv` for gaps, which mean the client froze. Compare with a
control route whose settings do not change.
