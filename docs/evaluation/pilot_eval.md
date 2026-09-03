# reproscope v0 pilot — replica evaluation

Generated 2026-09-03T22:58:59.682889+00:00. Papers: Axt_JournExpSocPsych_2018_zK2, Hertel_ClinPsychSci_2018_YabW, Hurst_EvoHumanBehavior_2017_yypJ, Ohtsubo_EvoHumanBehavior_2014_zlm2, Petersen_Cognition_2017_yJwG.

Match shares are over every claim × replica pair that Stage 1 scored in `match.json`, restricted to replicas that ran. A pair whose replica produced no value for the claim, or whose link step failed, is *abstained* and left out of the denominators. `n/a` means the metric could not be computed from the files present.

## Runs and reproduction, by family

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 10 | 10 | 0 | 0 | 934 | 100% | 72% | 78% | 90% | 88% |
| fable | 5 | 5 | 0 | 0 | 467 | 100% | 86% | 92% | 98% | 88% |
| glm | 10 | 10 | 0 | 0 | 934 | 100% | 86% | 92% | 96% | 91% |
| luna | 10 | 10 | 0 | 0 | 934 | 100% | 71% | 80% | 89% | 88% |
| opus | 10 | 10 | 0 | 0 | 934 | 100% | 87% | 93% | 98% | 91% |
| sol | 5 | 5 | 0 | 0 | 467 | 100% | 86% | 93% | 98% | 88% |
| frontier | 30 | 30 | 0 | 0 | 2,802 | 100% | 81% | 88% | 95% | 89% |
| cheap | 20 | 20 | 0 | 0 | 1,868 | 100% | 79% | 85% | 93% | 90% |

The last rows pool every replica in the tier (frontier = claude_p / codex subscription routes, cheap = opencode via OpenRouter); they are not averages of the family rates above. *no trace* is a replica directory without a `trace.json` — launched but not finished, distinct from *failed* (trace written, `ran` false).

## Band distribution (all scored pairs)

| family | A | B | C | fail | not found | abstained |
|---|---|---|---|---|---|---|
| deepseek | 658 | 53 | 10 | 188 | 0 | 25 |
| fable | 398 | 26 | 2 | 36 | 0 | 5 |
| glm | 782 | 55 | 4 | 71 | 0 | 22 |
| luna | 638 | 83 | 19 | 158 | 0 | 36 |
| opus | 786 | 52 | 4 | 63 | 0 | 29 |
| sol | 389 | 30 | 2 | 31 | 0 | 15 |
| frontier | 2211 | 191 | 27 | 288 | 0 | 85 |
| cheap | 1440 | 108 | 14 | 259 | 0 | 47 |

## Fixes, hardcoding audit, blinding

| family | fixes | minor | major | critical | unrated | clean | suspicious | hardcoded | audit n/r | blind hits |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 18 | 17 | 0 | 0 | 1 | 5 | 3 | 2 | 0 | 20 (10/10) |
| fable | 4 | 4 | 0 | 0 | 0 | 3 | 2 | 0 | 0 | 2 (5/5) |
| glm | 35 | 32 | 2 | 0 | 1 | 6 | 2 | 2 | 0 | 7 (10/10) |
| luna | 18 | 17 | 1 | 0 | 0 | 5 | 2 | 3 | 0 | 0 (10/10) |
| opus | 21 | 19 | 1 | 1 | 0 | 6 | 3 | 0 | 1 | 1 (10/10) |
| sol | 3 | 3 | 0 | 0 | 0 | 3 | 0 | 2 | 0 | 0 (5/5) |
| frontier | 46 | 43 | 2 | 1 | 0 | 17 | 7 | 5 | 1 | 3 (30/30) |
| cheap | 53 | 49 | 2 | 0 | 2 | 11 | 5 | 4 | 0 | 27 (20/20) |

Hardcoding columns count replicas by audit verdict. *blind hits* is the total of `run_checks.blind_transcript_hits` with the number of replicas reporting the field in brackets; traces written before the check existed do not report it.

## Cost and effort (replica calls only)

| family | tokens in | tokens out | cost $ (API) | list-price equiv $ | mean wall s |
|---|---|---|---|---|---|
| deepseek | 2,305,623 | 226,341 | 0.9081 | n/a | 548 |
| fable | 3,474,848 | 97,831 | 0.0000 | 12.9936 | 238 |
| glm | 1,802,175 | 167,500 | 0.5581 | n/a | 976 |
| luna | 813,341 | 0 | 0.0000 | n/a | 339 |
| opus | 11,622,620 | 244,818 | 0.0000 | 18.4592 | 288 |
| sol | 411,591 | 0 | 0.0000 | n/a | 360 |
| frontier | 16,322,400 | 342,649 | 0.0000 | 31.4528 | 309 |
| cheap | 4,107,798 | 393,841 | 1.4662 | n/a | 762 |

`cost $ (API)` is metered spend, which only the OpenRouter-backed families incur. `list-price equiv $` is what the subscription calls would have cost at API list price; the `claude -p` route reports it, the codex route does not, so codex-backed families show n/a there. The codex route also reports only a token total, which the ledger stores as `tokens_in`, so its `tokens out` reads 0.

## Per paper

### Axt_JournExpSocPsych_2018_zK2

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 2 | 0 | 0 | 92 | 100% | 82% | 96% | 93% | 100% |
| fable | 1 | 1 | 0 | 0 | 46 | 100% | 78% | 98% | 96% | 100% |
| glm | 2 | 2 | 0 | 0 | 92 | 100% | 76% | 95% | 91% | 100% |
| luna | 2 | 2 | 0 | 0 | 92 | 100% | 75% | 96% | 93% | 100% |
| opus | 2 | 2 | 0 | 0 | 92 | 100% | 78% | 98% | 96% | 100% |
| sol | 1 | 1 | 0 | 0 | 46 | 100% | 78% | 98% | 96% | 100% |

- Claims scored: 46
- Decision agreement (mean over claims): 0.910
- Numeric CV (median over claims): 0.000
- Focal quantity: mean = -0.120 (claim c221, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c221
  - replica values are on the mean scale, as the claim was reported
  - within deepseek (2 runs): -0.1184, -0.1184 — spread 0.0000
  - within glm (2 runs): -0.1184, -0.1184 — spread 0.0000
  - within luna (2 runs): -0.1184, -0.1184 — spread 0.0000
  - within opus (2 runs): -0.1184, -0.1184 — spread 0.0000
  - between-family range of family means: 0.0000
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.297, median 0.432, max 1.335
- Targeted reconstruction: not_triggered — The focal claim had at least half the usable replica rows in band A or B, at least one in band A, and a numeric CV of 0.2 or less.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 28 | 0.2329 | 21.4424 |
| 1 | 456 | 0.8505 | 13.5604 |
| 2 | 15 | 0.0135 | 9.0849 |
| 3 | 33 | 0.3643 | 2.4362 |
| total | 532 | 1.4612 | 46.5239 |

### Hertel_ClinPsychSci_2018_YabW

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 2 | 0 | 0 | 52 | 100% | 88% | 92% | 100% | 75% |
| fable | 1 | 1 | 0 | 0 | 26 | 100% | 92% | 92% | 100% | 75% |
| glm | 2 | 2 | 0 | 0 | 52 | 100% | 87% | 87% | 85% | 100% |
| luna | 2 | 2 | 0 | 0 | 52 | 100% | 86% | 86% | 100% | 75% |
| opus | 2 | 2 | 0 | 0 | 52 | 100% | 96% | 96% | 100% | 88% |
| sol | 1 | 1 | 0 | 0 | 26 | 100% | 92% | 92% | 100% | 75% |

- Claims scored: 26
- Decision agreement (mean over claims): 0.960
- Numeric CV (median over claims): 0.004
- Focal quantity: F = 6.200 (claim c092, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c070, c071, c092, c093, c094, c095
  - replica values are on the F scale, as the claim was reported
  - within deepseek (2 runs): 6.2037, 6.2037 — spread 0.0000
  - within glm (2 runs): 6.2037, 6.2037 — spread 0.0000
  - within luna (2 runs): 6.2037, 6.2065 — spread 0.0028
  - within opus (2 runs): 6.2037, 6.2037 — spread 0.0000
  - between-family range of family means: 0.0014
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.790, median 1.188, max 3.594
- Targeted reconstruction: not_triggered — The focal claim had at least half the usable replica rows in band A or B, at least one in band A, and a numeric CV of 0.2 or less.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 14 | 0.0365 | 7.4241 |
| 1 | 264 | 0.6051 | 12.8272 |
| 2 | 14 | 0.0244 | 8.8689 |
| 3 | 27 | 0.3431 | 1.6151 |
| total | 319 | 1.0091 | 30.7353 |

### Hurst_EvoHumanBehavior_2017_yypJ

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 2 | 0 | 0 | 516 | 100% | 66% | 70% | 66% | 91% |
| fable | 1 | 1 | 0 | 0 | 258 | 100% | 89% | 93% | 100% | 83% |
| glm | 2 | 2 | 0 | 0 | 516 | 100% | 89% | 93% | 100% | 83% |
| luna | 2 | 2 | 0 | 0 | 516 | 100% | 64% | 74% | 61% | 91% |
| opus | 2 | 2 | 0 | 0 | 516 | 100% | 89% | 93% | 100% | 83% |
| sol | 1 | 1 | 0 | 0 | 258 | 100% | 89% | 93% | 100% | 83% |

- Claims scored: 258
- Decision agreement (mean over claims): 0.780
- Numeric CV (median over claims): 0.268
- Focal quantity: r = -0.510 (claim c175, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c080, c118, c130, c166, c175, c197
  - replica values are on the r scale, as the claim was reported
  - within deepseek (2 runs): -0.5134, -0.5134 — spread 0.0000
  - within glm (2 runs): -0.5134, -0.5134 — spread 0.0000
  - within luna (2 runs): -0.5134, -0.5134 — spread 0.0000
  - within opus (2 runs): -0.5134, -0.5134 — spread 0.0000
  - between-family range of family means: 0.0000
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.929, median 1.196, max 1.607
- Targeted reconstruction: not_triggered — The focal claim had at least half the usable replica rows in band A or B, at least one in band A, and a numeric CV of 0.2 or less.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 14 | 0.0596 | 13.0040 |
| 1 | 2398 | 0.7975 | 22.0432 |
| 2 | 14 | 0.0156 | 13.5633 |
| 3 | 27 | 0.1704 | 1.6987 |
| total | 2453 | 1.0432 | 50.3092 |

### Ohtsubo_EvoHumanBehavior_2014_zlm2

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 2 | 0 | 0 | 40 | 100% | 35% | 57% | 93% | 94% |
| fable | 1 | 1 | 0 | 0 | 20 | 100% | 45% | 60% | 100% | 100% |
| glm | 2 | 2 | 0 | 0 | 40 | 100% | 48% | 72% | 100% | 100% |
| luna | 2 | 2 | 0 | 0 | 40 | 100% | 45% | 57% | 93% | 94% |
| opus | 2 | 2 | 0 | 0 | 40 | 100% | 48% | 62% | 100% | 100% |
| sol | 1 | 1 | 0 | 0 | 20 | 100% | 50% | 85% | 100% | 100% |

- Claims scored: 20
- Decision agreement (mean over claims): 0.750
- Numeric CV (median over claims): 0.133
- Focal quantity: d = 2.200 (claim c093, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c024, c040, c043, c049, c051, c052, c054, c076, c078, c081, c087, c088, c089, c090, c091, c092, c093, c099, c112, c116, c125, c130, c153
  - replica values are on the d scale, as the claim was reported
  - within deepseek (2 runs): 2.0083, 2.2645 — spread 0.2562
  - within glm (2 runs): 2.2645, 2.2645 — spread 0.0000
  - within luna (2 runs): 2.2645, 2.2645 — spread 0.0000
  - within opus (2 runs): 2.2645, 2.2645 — spread 0.0000
  - between-family range of family means: 0.1281
- Focal d — reported 2.200; replicas: deepseek_1 2.264, deepseek_2 2.008, fable_1 2.264, glm_1 2.264, glm_2 2.264, luna_1 2.264, luna_2 2.264, opus_1 2.264, opus_2 2.264, sol_1 2.264
  - Multi100 analysts (n = 6): min 1.142, median 2.007, max 3.106
- Targeted reconstruction: reachable — All seven quantities of analysis a20 are reproduced. The only change from the closest replica is dropping one of the two no-attention records with intimacy 2.25; every other choice in that script was already correct. Attempts 1-4 show the discrepancy is not an estimator choice: Welch, Hedges and d-from-t all leave the attention-group mean and SD and the df at their 30-record values. Attempt 5 shows the paper's own participant description already forces a 29-record sample and rules out 25 of the 30 possible exclusions. The residual gap is that the shared data file omits the suspicion variable, so three of the five description-consistent candidates are in the attention arm and do not reproduce the reported means.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 26 | 0.0781 | 16.5843 |
| 1 | 764 | 1.0382 | 28.8959 |
| 2 | 18 | 0.0092 | 15.6018 |
| 3 | 33 | 0.2182 | 1.8502 |
| total | 841 | 1.3438 | 62.9321 |

### Petersen_Cognition_2017_yJwG

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 2 | 0 | 0 | 234 | 100% | 87% | 91% | 98% | 87% |
| fable | 1 | 1 | 0 | 0 | 117 | 100% | 90% | 93% | 98% | 87% |
| glm | 2 | 2 | 0 | 0 | 234 | 100% | 89% | 93% | 98% | 87% |
| luna | 2 | 2 | 0 | 0 | 234 | 100% | 89% | 92% | 98% | 87% |
| opus | 2 | 2 | 0 | 0 | 234 | 100% | 91% | 94% | 98% | 90% |
| sol | 1 | 1 | 0 | 0 | 117 | 100% | 89% | 92% | 98% | 87% |

- Claims scored: 117
- Decision agreement (mean over claims): 0.800
- Numeric CV (median over claims): 0.000
- Focal quantity: d = 0.890 (claim c008, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c006, c007, c008, c024, c030, c033, c050, c056, c070, c072, c078, c093, c098, c105, c110
  - replica values are on the d scale, as the claim was reported
  - within deepseek (2 runs): 0.8897, 0.8900 — spread 0.0003
  - within glm (2 runs): 0.8897, 0.8897 — spread 0.0000
  - within luna (2 runs): 0.8897, 0.8897 — spread 0.0000
  - within opus (2 runs): 0.8897, 0.8897 — spread 0.0000
  - between-family range of family means: 0.0001
- Focal d — reported 0.890; replicas: deepseek_1 0.890, deepseek_2 0.890, fable_1 0.890, glm_1 0.890, glm_2 0.890, luna_1 0.890, luna_2 0.890, opus_1 0.890, opus_2 0.890, sol_1 0.890
  - Multi100 analysts (n = 5): min 1.812, median 1.812, max 2.279
- Targeted reconstruction: not_triggered — The focal claim had at least half the usable replica rows in band A or B, at least one in band A, and a numeric CV of 0.2 or less.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 17 | 0.0391 | 10.9557 |
| 1 | 1060 | 0.8463 | 11.1578 |
| 2 | 9 | 0.0132 | 3.6777 |
| 3 | 21 | 0.1504 | 0.8900 |
| total | 1107 | 1.0490 | 26.6813 |
