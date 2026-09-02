# reproscope v0 pilot — replica evaluation

Generated 2026-09-02T15:48:26.156411+00:00. Papers: Axt_JournExpSocPsych_2018_zK2, Hertel_ClinPsychSci_2018_YabW, Hurst_EvoHumanBehavior_2017_yypJ, Ohtsubo_EvoHumanBehavior_2014_zlm2, Petersen_Cognition_2017_yJwG.

Match shares are over every claim × replica pair that Stage 1 scored in `match.json`, restricted to replicas that ran. A pair whose replica could not bind the claim to the data counts as *not found*, not as a failed match. `n/a` means the metric could not be computed from the files present.

## Runs and reproduction, by family

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 0 | 1 | 1 | n/a | n/a | n/a | n/a | n/a | n/a |
| fable | 1 | 1 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| glm | 2 | 0 | 0 | 2 | n/a | n/a | n/a | n/a | n/a | n/a |
| opus | 2 | 2 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| sol | 1 | 1 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| frontier | 4 | 4 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| cheap | 4 | 0 | 1 | 3 | n/a | n/a | n/a | n/a | n/a | n/a |

The last rows pool every replica in the tier (frontier = claude_p / codex subscription routes, cheap = opencode via OpenRouter); they are not averages of the family rates above. *no trace* is a replica directory without a `trace.json` — launched but not finished, distinct from *failed* (trace written, `ran` false).

## Band distribution (all scored pairs)

| family | A | B | C | fail | not found |
|---|---|---|---|---|---|
| deepseek | n/a | n/a | n/a | n/a | n/a |
| fable | n/a | n/a | n/a | n/a | n/a |
| glm | n/a | n/a | n/a | n/a | n/a |
| opus | n/a | n/a | n/a | n/a | n/a |
| sol | n/a | n/a | n/a | n/a | n/a |
| frontier | n/a | n/a | n/a | n/a | n/a |
| cheap | n/a | n/a | n/a | n/a | n/a |

## Fixes, hardcoding audit, blinding

| family | fixes | minor | major | critical | unrated | clean | suspicious | hardcoded | audit n/r | blind hits |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 4 (1/2) |
| fable | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 (1/1) |
| glm | n/a | n/a | n/a | n/a | n/a | 0 | 0 | 0 | 2 | n/a |
| opus | 7 | 7 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 (2/2) |
| sol | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 (1/1) |
| frontier | 8 | 8 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 (4/4) |
| cheap | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 3 | 4 (1/4) |

Hardcoding columns count replicas by audit verdict. *blind hits* is the total of `run_checks.blind_transcript_hits` with the number of replicas reporting the field in brackets; traces written before the check existed do not report it.

## Cost and effort (replica calls only)

| family | tokens in | tokens out | cost $ (API) | list-price equiv $ | mean wall s |
|---|---|---|---|---|---|
| deepseek | 132,111 | 10,975 | 0.0397 | n/a | 303 |
| fable | 397,372 | 11,416 | 0.0000 | 1.7435 | 147 |
| glm | 224,448 | 16,570 | 0.0516 | n/a | 472 |
| opus | 1,546,192 | 32,317 | 0.0000 | 2.6447 | 208 |
| sol | 59,141 | 0 | 0.0000 | n/a | 272 |
| frontier | 2,002,705 | 43,733 | 0.0000 | 4.3882 | 209 |
| cheap | 356,559 | 27,545 | 0.0912 | n/a | 387 |

`cost $ (API)` is metered spend, which only the OpenRouter-backed families incur. `list-price equiv $` is what the subscription calls would have cost at API list price; the `claude -p` route reports it, the codex route does not, so codex-backed families show n/a there. The codex route also reports only a token total, which the ledger stores as `tokens_in`, so its `tokens out` reads 0.

## Per paper

### Axt_JournExpSocPsych_2018_zK2

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| (no replicas) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

- Claims scored: n/a
- Decision agreement (mean over claims): n/a
- Numeric CV (median over claims): n/a
- Focal quantity: n/a
  - within-family focal spread: n/a (no family with two runs reporting the focal value)
  - between-family range of family means: n/a
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.297, median 0.432, max 1.335
- Targeted reconstruction: n/a

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 15 | 0.2025 | 0.0000 |
| total | 15 | 0.2025 | 0.0000 |

### Hertel_ClinPsychSci_2018_YabW

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| (no replicas) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

- Claims scored: n/a
- Decision agreement (mean over claims): n/a
- Numeric CV (median over claims): n/a
- Focal quantity: F = 6.200 (claim c078, bound offline from the manifest focal claim)
  - focal claim set (the *focal A+B* column above pools these): c005, c051, c054, c055, c056, c078, c079
  - within-family focal spread: n/a (no family with two runs reporting the focal value)
  - between-family range of family means: n/a
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.790, median 1.188, max 3.594
- Targeted reconstruction: n/a

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 10 | 0.0584 | 3.2946 |
| total | 10 | 0.0584 | 3.2946 |

### Hurst_EvoHumanBehavior_2017_yypJ

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| (no replicas) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

- Claims scored: n/a
- Decision agreement (mean over claims): n/a
- Numeric CV (median over claims): n/a
- Focal quantity: n/a
  - within-family focal spread: n/a (no family with two runs reporting the focal value)
  - between-family range of family means: n/a
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 0.929, median 1.196, max 1.607
- Targeted reconstruction: n/a

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 2 | 0.0596 | 0.0000 |
| total | 2 | 0.0596 | 0.0000 |

### Ohtsubo_EvoHumanBehavior_2014_zlm2

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 2 | 0 | 1 | 1 | n/a | n/a | n/a | n/a | n/a | n/a |
| fable | 1 | 1 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| glm | 2 | 0 | 0 | 2 | n/a | n/a | n/a | n/a | n/a | n/a |
| opus | 2 | 2 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| sol | 1 | 1 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

- Claims scored: n/a
- Decision agreement (mean over claims): n/a
- Numeric CV (median over claims): n/a
- Focal quantity: d = 2.200 (claim c093, bound offline from the manifest focal claim)
  - focal claim set (the *focal A+B* column above pools these): c087, c089, c091, c093, c110
  - within-family focal spread: n/a (no family with two runs reporting the focal value)
  - between-family range of family means: n/a
- Focal d — reported 2.200; replicas: n/a
  - Multi100 analysts (n = 6): min 1.142, median 2.007, max 3.106
- Targeted reconstruction: n/a

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 26 | 0.0781 | 16.5843 |
| 1 | 16 | 0.1176 | 4.3882 |
| total | 42 | 0.1957 | 20.9725 |

### Petersen_Cognition_2017_yJwG

| family | launched | ran | failed | no trace | pairs scored | found | A | A+B | headline A+B | focal A+B |
|---|---|---|---|---|---|---|---|---|---|---|
| (no replicas) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

- Claims scored: n/a
- Decision agreement (mean over claims): n/a
- Numeric CV (median over claims): n/a
- Focal quantity: n/a
  - within-family focal spread: n/a (no family with two runs reporting the focal value)
  - between-family range of family means: n/a
- Focal d — reported n/a; replicas: n/a
  - Multi100 analysts (n = 5): min 1.812, median 1.812, max 2.279
- Targeted reconstruction: n/a

| stage | calls | cost $ (API) | list-price equiv $ |
|---|---|---|---|
| 0 | 5 | 0.0391 | 2.5642 |
| total | 5 | 0.0391 | 2.5642 |
