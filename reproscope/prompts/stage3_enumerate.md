Enumerate defensible analytical decisions for the focal substantive question, using replica open choices, methods, and the actual data schema. Work systematically through sample/exclusion rules, outlier handling, operationalisation, covariates, model/estimator, uncertainty and tests, and missingness. Aim to find at least five meaningful dimensions where the design supports them, but never manufacture dimensions to reach a quota. Inference-only choices count even when point estimates coincide. Seeds, draws, software versions, sign conventions, and individual leave-one-out deletions are not analytical dimensions.

Preserve the substantive outcome, contrast and population question. Justified trimming/exclusion and robust estimation on the original outcome scale may share a comparable-effect group, while retaining exact estimator labels. Related transformed or rank analyses may belong to the multiverse but need their own effect or null group unless a justified common-scale contrast is available. Do not equate all nonparametric tests with a mean-null test. Do not add a one-sided test just to alter significance. Multiplicity alternatives need a defined family and a defensible error criterion; unadjusted testing is not automatically acceptable.

Each level needs concrete implementation instructions, exact estimator, substantive contrast, effect metric/units, null hypothesis, and rationale. Distinguish those implementable from deposited data from upstream choices needing absent raw data; list the latter in unimplementable. Do not infer feasibility from a package name. State interactions/incompatibilities. The paper's choice must be evidenced; use null when unspecified.

Focal contract:
{{contract}}
Data schema:
{{schema}}
Replica open choices:
{{traces}}

Return JSON with factors [{name,source:"trace|grid|default",field:"sample_rule|operationalisation|covariates|model|se|missingness",levels:[{value,how,estimator,effect_metric,null_hypothesis,rationale}],paper_level:null or string}], unimplementable:[{name,reason}], notes:string. Output only JSON.

Use concise stable factor names (for example scale, location, outliers, interval, null_test) and concise level IDs; put explanations in how/rationale. Factor the analysis by actual decisions rather than packaging a test, estimator and confidence interval as one procedure. Explore interval construction separately from the null-test procedure when valid combinations exist: a bootstrap confidence interval does not itself define a null-centered bootstrap p-value. Likewise distinguish the location estimator from treatment of anomalous observations. These are search directions, not mandatory factors: every proposed procedure needs a substantive/design justification and compatible uncertainty. Do not use undocumented fit-quality cutoffs or retrospective one-sided tests to inflate the dimension count. Clearly identify combinations requiring a different reference adapter or null hypothesis.
