# reproscope v0 pilot — replica evaluation

Generated 2026-09-03T19:15:06.743743+00:00. Papers: Axt_JournExpSocPsych_2018_zK2, Hertel_ClinPsychSci_2018_YabW, Hurst_EvoHumanBehavior_2017_yypJ, Ohtsubo_EvoHumanBehavior_2014_zlm2, Petersen_Cognition_2017_yJwG.

Match shares are over every claim × replica pair that Stage 1 scored in `match.json`, restricted to replicas that ran. A pair whose replica produced no value for the claim, or whose link step failed, is *abstained* and left out of the denominators. `n/a` means the metric could not be computed from the files present.

## Runs and reproduction, by family

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 10 | 8 | 2 | 0 | 700 | 100% | 66% | 73% | 76% | 89% |
| fable | 5 | 5 | 0 | 0 | 467 | 100% | 82% | 88% | 83% | 88% |
| glm | 10 | 10 | 0 | 0 | 934 | 100% | 80% | 86% | 73% | 91% |
| luna | 10 | 10 | 0 | 0 | 934 | 100% | 65% | 74% | 64% | 88% |
| opus | 10 | 10 | 0 | 0 | 934 | 100% | 83% | 89% | 83% | 91% |
| sol | 5 | 5 | 0 | 0 | 467 | 100% | 78% | 85% | 67% | 88% |
| frontier | 30 | 30 | 0 | 0 | 2,802 | 100% | 76% | 83% | 74% | 89% |
| cheap | 20 | 18 | 2 | 0 | 1,634 | 100% | 74% | 80% | 74% | 90% |

The last rows pool every replica in the tier (frontier = claude_p / codex subscription routes, cheap = opencode via OpenRouter); they are not averages of the family rates above. *no trace* is a replica directory without a `trace.json` — launched but not finished, distinct from *failed* (trace written, `ran` false).

## Band distribution (all scored pairs)

| family | A | B | C | fail | not found | abstained |
|---|---|---|---|---|---|---|
| deepseek | 461 | 43 | 9 | 182 | 0 | 5 |
| fable | 380 | 26 | 2 | 54 | 0 | 5 |
| glm | 729 | 55 | 4 | 124 | 0 | 22 |
| luna | 580 | 82 | 18 | 218 | 0 | 36 |
| opus | 750 | 52 | 4 | 99 | 0 | 29 |
| sol | 354 | 30 | 2 | 66 | 0 | 15 |
| frontier | 2064 | 190 | 26 | 437 | 0 | 85 |
| cheap | 1190 | 98 | 13 | 306 | 0 | 27 |

## Fixes, hardcoding audit, blinding

| family | fixes | minor | major | critical | unrated | clean | suspicious | hardcoded | audit n/r | blind hits |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 20 | 19 | 0 | 0 | 1 | 5 | 3 | 2 | 0 | 20 (10/10) |
| fable | 4 | 4 | 0 | 0 | 0 | 3 | 2 | 0 | 0 | 2 (5/5) |
| glm | 35 | 32 | 2 | 0 | 1 | 6 | 2 | 2 | 0 | 7 (10/10) |
| luna | 18 | 17 | 1 | 0 | 0 | 5 | 2 | 3 | 0 | 0 (10/10) |
| opus | 21 | 19 | 1 | 1 | 0 | 6 | 3 | 0 | 1 | 1 (10/10) |
| sol | 3 | 3 | 0 | 0 | 0 | 3 | 0 | 2 | 0 | 0 (5/5) |
| frontier | 46 | 43 | 2 | 1 | 0 | 17 | 7 | 5 | 1 | 3 (30/30) |
| cheap | 55 | 51 | 2 | 0 | 2 | 11 | 5 | 4 | 0 | 27 (20/20) |

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
| deepseek | 2 | 2 | 0 | 0 | 92 | 100% | 70% | 83% | 71% | 100% |
| fable | 1 | 1 | 0 | 0 | 46 | 100% | 63% | 83% | 71% | 100% |
| glm | 2 | 2 | 0 | 0 | 92 | 100% | 61% | 79% | 66% | 100% |
| luna | 2 | 2 | 0 | 0 | 92 | 100% | 63% | 83% | 71% | 100% |
| opus | 2 | 2 | 0 | 0 | 92 | 100% | 63% | 83% | 71% | 100% |
| sol | 1 | 1 | 0 | 0 | 46 | 100% | 63% | 83% | 71% | 100% |

- Claims scored: 46
- Decision agreement (mean over claims): 0.770
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
| 1 | 453 | 0.8472 | 13.2957 |
| 2 | 14 | 0.0135 | 8.0086 |
| 3 | 25 | 0.3097 | 1.8948 |
| total | 520 | 1.4033 | 44.6415 |

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
| 1 | 263 | 0.6051 | 12.5729 |
| 2 | 13 | 0.0244 | 7.3623 |
| 3 | 19 | 0.1990 | 0.9954 |
| total | 309 | 0.8650 | 28.3547 |

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
| 1 | 2397 | 0.7975 | 21.7277 |
| 2 | 13 | 0.0156 | 12.0169 |
| 3 | 19 | 0.1156 | 0.9592 |
| total | 2443 | 0.9883 | 47.7078 |

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
- Decision agreement (mean over claims): n/a
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
- Targeted reconstruction: reachable — The whole gap between the blind analysts and the paper is the sample size, not the model. The closest replica's analytical choices (item-mean intimacy, Student t, pooled-SD Cohen's d) were already the paper's; it kept all 30 records because the deception-suspicion exclusion cannot be coded from the file, giving t(28) = 6.20 and d = 2.26. Attempts 2-5 varied every ambiguity the contract flags (Welch, d-from-t, Hedges g, sum vs mean aggregation) and none of them reached d = 2.20: Welch and d-from-t leave d at 2.264 (the two groups have near-equal variance and n), Hedges gives 2.203 but leaves t at 6.20 with df = 28, and the sum aggregation destroys the reported means. Only dropping one no-attention record reproduces t, df, both means, both SDs and d at once. The attention condition's mean and SD (4.583, 0.816) are identical in the file and in the paper, which independently confirms the excluded participant is in the no attention condition. Attempt 6 shows the search was not fitted to the target: the Method section, without any results, narrows the exclusion to five records, and three of those five (the attention-condition candidates) miss the reported values. Attempt 7 stops at a full match, one attempt inside the budget of eight.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 26 | 0.0781 | 16.5843 |
| 1 | 759 | 1.0328 | 25.6307 |
| 2 | 16 | 0.0092 | 12.6584 |
| 3 | 25 | 0.1435 | 1.1843 |
| total | 826 | 1.2636 | 56.0576 |

### Petersen_Cognition_2017_yJwG

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 0 | 2 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| fable | 1 | 1 | 0 | 0 | 117 | 100% | 80% | 84% | 76% | 87% |
| glm | 2 | 2 | 0 | 0 | 234 | 100% | 71% | 75% | 57% | 87% |
| luna | 2 | 2 | 0 | 0 | 234 | 100% | 66% | 70% | 48% | 87% |
| opus | 2 | 2 | 0 | 0 | 234 | 100% | 80% | 84% | 76% | 90% |
| sol | 1 | 1 | 0 | 0 | 117 | 100% | 62% | 66% | 37% | 87% |

- Claims scored: 117
- Decision agreement (mean over claims): 0.430
- Numeric CV (median over claims): 0.000
- Focal quantity: d = 0.890 (claim c008, stage3/focal.json)
  - focal claim set (the *focal A+B* column above pools these): c006, c007, c008, c024, c030, c033, c050, c056, c070, c072, c078, c093, c098, c105, c110
  - replica values are on the d scale, as the claim was reported
  - within glm (2 runs): 0.8897, 0.8897 — spread 0.0000
  - within luna (2 runs): 0.8897, 0.8897 — spread 0.0000
  - within opus (2 runs): 0.8897, 0.8897 — spread 0.0000
  - between-family range of family means: 0.0000
- Focal d — reported 0.890; replicas: fable_1 0.890, glm_1 0.890, glm_2 0.890, luna_1 0.890, luna_2 0.890, opus_1 0.890, opus_2 0.890, sol_1 0.890
  - Multi100 analysts (n = 5): min 1.812, median 1.812, max 2.279
- Targeted reconstruction: not_triggered — The focal claim had at least half the usable replica rows in band A or B, at least one in band A, and a numeric CV of 0.2 or less.

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 17 | 0.0391 | 10.9557 |
| 1 | 1055 | 0.8360 | 10.8692 |
| 2 | 6 | 0.0073 | 1.5428 |
| 3 | 12 | 0.0925 | 0.3690 |
| total | 1090 | 0.9750 | 23.7368 |
