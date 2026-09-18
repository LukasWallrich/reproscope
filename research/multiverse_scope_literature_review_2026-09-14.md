# Multiverse scope: trimming, comparable effects, inference, and influence

Reviewed 14 September 2026. Targeted methodological literature review for reproscope; AI-assisted, without independent human verification. The recommendations below are pipeline design decisions, not claims that the current implementation already satisfies them.

The pipeline should admit justified trimming and outlier handling into its analytical multiverse. It should group results by a stated substantive contrast and interpretable effect scale, retaining estimator and exclusion labels. Exact equality of statistical functionals is too restrictive as a universal display rule; identical units alone are insufficient. Related inference procedures deserve their own reporting even when their point estimates coincide. Participant-deletion diagnostics should remain outside analytical specification counts.

The literature supports these distinctions, but does not prescribe one universal grouping algorithm. The operational rules below therefore separate evidence from our implementation recommendations.

## Evidence and its limits

| Source and checked location | Relevant guidance | Limit of the evidence |
|---|---|---|
| [Steegen et al. (2016)](https://doi.org/10.1177/1745691616658637), opening rationale and discussion | Multiverse analysis explicitly covers reasonable exclusion, transformation, and coding decisions. The authors connect it to examining results with and without outliers. Its central purpose is transparency about consequential processing choices; it is not inherently a formal evidential test. | Supports including outlier handling, without endorsing every trimming threshold or declaring all resulting estimands identical. |
| [Simonsohn et al. (2020)](https://doi.org/10.1038/s41562-020-0912-z), identification criteria, Table 1, Figure 2, and Steps 2–3 | Specifications must be theoretically sensible, statistically valid, and nonredundant. The hurricane example varies exclusions and regression models, including a logged outcome. It reports a common predicted-deaths contrast, explicitly making continuous and discrete predictor operationalisations comparable. Descriptive curves and joint inference are separate steps. | Common-scale construction requires a justified mapping. A collection of different coefficients is not automatically comparable, and the inferential procedure is not universal. |
| [Del Giudice and Gangestad (2021)](https://doi.org/10.1177/2515245920954925), pp. 6–7 and 11–13 | Evaluate measurement, effect, and power/precision equivalence. Type E alternatives are practically equivalent and belong in a homogeneous multiverse; Type N alternatives are nonequivalent and should not be treated as arbitrary substitutes; Type U requires exploratory treatment. Their worked principled analysis retains alternative outlier cutoffs as Type E. | Their retained cutoffs change sample size little. This is conditional justification, not a general endorsement of aggressive deletion. Equivalence concerns practical comparability, not identical realised estimates. |
| [Short et al. (2026)](https://doi.org/10.1177/25152459261434881), Step 2, Table 2, and “Existence and measurement of equivalence” | Distinguish whether a pipeline is defensible individually from whether alternatives are interchangeable for a specified purpose. Broader defensible multiverses can map analytical diversity; a single-effect robustness claim needs closer comparability. Equivalence criteria remain contested and must be explicit. | This is multidisciplinary guidance, not a settled numerical threshold or universal requirement to prune every multiverse to one exact functional. |
| [Godwin et al. (2025)](https://doi.org/10.3758/s13428-025-02689-0), decision point 3, Results, and Figures 2–3 | An applied reading-data multiverse varies no removal versus 2.5/3-SD exclusions, with grand-mean, participant, or participant-by-condition cutoffs. It also varies outcome modelling and separately displays logged-model coefficients in follow-up figures. | This establishes actual practice. Its SD-based trimming is not a fixed-percentage trimmed mean, and its modelling/display choices are not all methodological recommendations for this pipeline. |
| [Semken and Rossell (2022)](https://doi.org/10.1111/rssc.12578), author version §§2.1–2.2 and 3.1 | Show how indiscriminate aggregation across covariate specifications and heterogeneous effects can mislead. A simulation with an omitted relevant control produces severe false-positive behaviour. They also explain how parameterisation can preserve the interpretation of a contrast across models. | The critique concerns specified aggregation and modelling problems. It does not establish that all descriptive specification curves or every multiverse inferential method are invalid. |
| [Klau et al. (2023)](https://doi.org/10.15626/MP.2020.2556), publisher abstract | Distinguish variation due to preprocessing, model choices, and sampling. These are different sources of instability, even when investigated together. | Only the abstract and bibliographic record were checked here. This supports separating sources of variation, not a claimed explicit prohibition on leave-one-out multiverses. |

## Trimming and the meaning of a common curve

There are two different questions: whether an alternative is worth including, and whether its numerical effect can be interpreted alongside another effect. The foundational inclusion of exclusions answers the first; it does not settle the second. [Steegen et al. (2016)](https://doi.org/10.1177/1745691616658637)

Our proposed policy is to allow the ordinary mean and a justified trimmed mean of the same raw paired differences in one **raw-effect sensitivity curve**, with the trimming rule visible. Do not describe that curve as repeated estimation of one mathematically identical population functional. For a quantile function Q, the population α-trimmed mean is `(1 − 2α)⁻¹ ∫[α,1−α] Q(u) du`; it generally differs from the unrestricted mean. This mathematical distinction need not create a separate operational target for every cleaning rule.

For this pipeline, retain a common group when the intended contrast, outcome, direction, and units remain interpretable together and the alternative is justified as handling extreme observations or contamination. Record both the substantive target and exact estimator. Split or flag alternatives that deliberately redefine the population or shift the substantive question. A symmetric location setting and a strongly skewed distribution with meaningful tails need different justifications for trimming.

For paired data, record whether trimming applies to within-person differences, trials, participants, or each condition separately. These operations are not interchangeable. Preserve pairing and validate uncertainty for the actual estimator; an ordinary paired-t standard error cannot simply accompany a trimmed point estimate. The currently registered engine trims 20% from each tail of paired differences. The reviewed literature does **not** establish that this particular percentage is appropriate for the development paper.

Transformed models may also produce comparable effects after an explicit common-contrast calculation. A log coefficient or ratio should not appear on a raw-difference axis merely after changing its label. The SCA example provides a precedent for deriving comparable contrasts across specifications. [Simonsohn et al. (2020)](https://doi.org/10.1038/s41562-020-0912-z)

## Proposed reporting and classification contract

This contract is our synthesis for implementation, not a taxonomy quoted from a single paper.

| Output | Admission rule | Required display |
|---|---|---|
| Comparable-effect curve | Defensible alternatives addressing a common substantive contrast on an interpretable common scale, including justified raw-scale trimming/exclusion choices | Effect, uncertainty interval and method, sample size, exclusion/estimator labels, and a decision dashboard. Permit filtering by estimator. |
| Inference robustness | Defensible tests or uncertainty procedures, including methods lacking a comparable effect estimate | Named null/alternative, direction, p-value or other evidence measure, adjustment family, assumptions, and link to the corresponding effect specification where available. Group different nulls separately. |
| Related-effect panels | Useful analytical alternatives whose effects cannot defensibly be mapped to the focal scale or interpretation | Their own units, contrast, estimator, and intervals. Explain the relation to the focal result without pooling magnitudes. |
| Influence diagnostics | Structured deletions or perturbations intended to identify influential observations | Matched-baseline changes and influential observation identifiers; separate counts and denominators. |

A specification can contribute to both the effect curve and inference display. These are output capabilities, not mutually exclusive bins. An inference-only choice can be a legitimate analytical dimension: identical point estimates do not imply equivalent interval coverage or testing behaviour. Conversely, different names for the same procedure, random seeds, and internal bootstrap draws do not create analytical dimensions.

Do not classify every nonparametric procedure as a test of the same mean null. Require the generator to identify its target and assumptions. A related test may inform the substantive conclusion while needing a separate null group. Nor should all nonparametric estimators be excluded from effect displays if they supply a meaningful comparable estimate.

For multiplicity, define the family and error criterion before varying procedures. Unadjusted, Holm, and Bonferroni results are not automatically three equally defensible choices in every design. Store pointwise versus simultaneous interval coverage independently from p-value adjustment. Incompatible estimator/test/interval combinations must be rejected at the whole-pipeline level.

Use a separate assessment of practical comparability, with documented reasons, instead of classifying results by whether they happen to agree. The distinction between individual defensibility and relative equivalence is explicit in current guidance; implementation criteria remain unsettled. [Short et al. (2026)](https://doi.org/10.1177/25152459261434881)

## Leave-one-out and aggregation

The proposed exclusion of individual participant deletions from analytical dimensions is a design inference. This targeted search did not establish a universal literature rule banning every use of leave-one-out. The relevant distinction is between choosing an analysis rule and examining sensitivity to particular observations. Sampling variation is also conceptually separate from preprocessing and model variation. [Klau et al. (2023)](https://doi.org/10.15626/MP.2020.2556)

For an analytical specification s and deleted independent unit i, compute `Δ(s,i) = estimate(s,−i) − estimate(s)`. Summarise within each matched baseline: deletion count and completeness, maximum absolute change and responsible IDs, signed change range, change divided by baseline SE where defined, and sign/interval-side/p-threshold changes. Threshold-change counts are descriptive diagnostics, not error probabilities.

If diagnostics cover several analytical specifications, retain those baseline-specific summaries. A further worst-case summary must identify its baseline and units. Do not average raw differences with ratios or count n deletions as n analytical votes. The current implementation evaluates selected baselines only; that scope must remain explicit.

A prespecified outlier rule can be an analytical choice, including a defensible rule informed by an influence measure. Deleting every participant in turn is a diagnostic schedule. Bootstrap and jackknife replicates are internal computations. Leave-one-out cross-validation can be part of a prediction method in another task, so the generator should reject deletion-as-specification rather than blindly reject every occurrence of the phrase.

## Reporting useful robustness without overstating evidence

Report the estimated magnitudes, uncertainty, decision combinations, failures, and assumptions behind any change in conclusion. A percentage of significant specifications is a description of the chosen grid. It is not a probability that the finding is true or a binomial sample of independent replications. Formal aggregation needs a defined target and valid treatment of dependent results; heterogeneous or misspecified models can defeat a superficially reassuring aggregate. [Semken and Rossell (2022)](https://doi.org/10.1111/rssc.12578)

For reproscope, report both the total analytical decision count and the counts within each effect/null group. Count a factor when it has at least two defensible, executable alternatives whose procedures differ meaningfully, even if this dataset produces the same estimate. Distinguish structural redundancy from coincident results. Show inactive or pinned factors explicitly.

No minimum of five dimensions was established by this review. The user’s >4-dimension requirement is a development target, not a literature validity criterion. It should motivate a search for meaningful alternatives and an honest shortfall when unavailable, rather than extra seeds, deletion levels, arbitrary thresholds, or duplicate corrections.

## Implementation reconciliation tasks

The following work remains; recording this review does not validate a revised run.

1. **Generator and screen:** update `stage3_enumerate.md` and `stage3_screen.md` to request substantive contrast, exact estimator, effect scale/mapping, null, defensibility rationale, comparability rationale, and role. Explicitly reject observation deletions and internal resampling as specification levels. Apply compatibility checks to complete pipelines.
2. **Execution and report:** replace the automatic `trim20 → alternative_estimand` classification in `scoped_multiverse.py` with the reviewed grouping policy. Preserve estimator metadata and uncertainty validation. Implement the linked effect/inference displays and retain separate diagnostic outputs in `multiverse_summary.py` and report rendering.
3. **Generation validation:** the registered paired engine bypasses ordinary stage-3 enumeration/screening. Its hand-coded alternatives therefore do not establish that the general generator finds defensible dimensions. Validate the actual generation path separately.
4. **Dimension acceptance:** reconcile “result-moving” wording and global five-axis checks with meaningful procedural alternatives and per-group counts. Check whether multiplicity and interval choices are defensible and compatible for the actual claim family.
5. **Benchmark:** use prespecified synthetic paired scenarios with known targets: a symmetric location shift, contamination, genuine skew/tail heterogeneity, and influential observations. Check grouping, pairing, estimator/interval calibration, rejection of invalid combinations, and diagnostic denominators. Add cases where valid uncertainty methods share a point estimate and where transformed effects do/do not have a justified common-scale mapping. Do not select scenarios or thresholds to make this run pass.
6. **Active documentation:** reconcile `docs/PILOT_DESIGN.md`, run acceptance language, and report labels with the implemented contract. Preserve historical receipts as evidence of the rules they actually checked. “Five dimensions” must identify whether it spans several effect/null groups.
7. **Separate review scope:** rename the default paper-without-code check to clear statistical analysis errors and clear interpretation errors. This literature review does not decide whether a paper’s causal interpretation is erroneous; causal assumptions matter here only when needed to establish comparability of alternatives.

## Search and source audit

This was a targeted narrative review, not a systematic review. Searches on 14 September 2026 combined multiverse/specification-curve terms with estimand, equivalence, trimming, outlier, inference, leave-one-out, and sampling uncertainty, followed by primary-source and reference checks. Selection prioritised foundational methods, explicit scope guidance, a direct exclusion/trimming application, and an inferential critique. No claim of exhaustive coverage is made.

Publisher full text was consulted for Steegen, Short, and Godwin; author PDFs for Simonsohn and Del Giudice; and [Semken and Rossell’s author version](https://arxiv.org/abs/2201.05381v2), §§2–3, alongside the published bibliographic record. Simonsohn’s PDF page containing Table 1 and Step 2 was visually checked. Klau was used only at abstract level. Some repository endpoints failed; author/publisher alternatives were used. No paid model or API calls were needed.

Full references and access points:

- Steegen, S., Tuerlinckx, F., Gelman, A., & Vanpaemel, W. (2016). Increasing transparency through a multiverse analysis. *Perspectives on Psychological Science, 11*, 702–712. [DOI](https://doi.org/10.1177/1745691616658637).
- Simonsohn, U., Simmons, J. P., & Nelson, L. D. (2020). Specification curve analysis. *Nature Human Behaviour, 4*, 1208–1214. [DOI](https://doi.org/10.1038/s41562-020-0912-z); [author PDF](https://faculty.wharton.upenn.edu/wp-content/uploads/2016/11/33-Simonsohn-Simmons-Nelson-2020.pdf).
- Del Giudice, M., & Gangestad, S. W. (2021). A traveler’s guide to the multiverse: Promises, pitfalls, and a framework for the evaluation of analytic decisions. *Advances in Methods and Practices in Psychological Science, 4*(1). [DOI](https://doi.org/10.1177/2515245920954925); [author PDF](https://marcodg.net/wp-content/uploads/2021/01/delgiudice_gangestad_2021_guide-to-the-multiverse_ampps.pdf).
- Short, C. A., et al. (2026). Multicurious: A multidisciplinary guide to multiverse analysis. *Advances in Methods and Practices in Psychological Science*. [DOI and publisher full text](https://doi.org/10.1177/25152459261434881).
- Godwin, H. J., Lee, C. E., & Drieghe, D. (2025). A multiverse analysis of cleaning and analyzing procedures of eye movement data during reading. *Behavior Research Methods, 57*, Article 164. [DOI and publisher full text](https://doi.org/10.3758/s13428-025-02689-0).
- Semken, C., & Rossell, D. (2022). Specification analysis for technology use and teenager well-being: Statistical validity and a Bayesian proposal. *Journal of the Royal Statistical Society: Series C, 71*, 1330–1355. [DOI](https://doi.org/10.1111/rssc.12578).
- Klau, S., Schönbrodt, F. D., Patel, C. J., Ioannidis, J. P. A., Boulesteix, A.-L., & Hoffmann, S. (2023). Comparing the vibration of effects due to model, data pre-processing and sampling uncertainty on a large data set in personality psychology. *Meta-Psychology, 7*. [DOI](https://doi.org/10.15626/MP.2020.2556); [publisher abstract](https://open.lnu.se/index.php/metapsychology/article/view/2556).

Research-note reconciliation: the earlier `research_statreview_multiverse.md` incorrectly restricted the Del Giudice–Gangestad framework to Type U decisions. Both occurrences are corrected alongside this review. Type E is explicitly suitable for a homogeneous multiverse; Type U signals uncertainty requiring exploratory treatment, not privileged admission. Other claims in that broader report were not comprehensively re-audited here.
