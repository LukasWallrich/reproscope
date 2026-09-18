## Schema: separate fields

Use two separate fields. A scope flag cannot hold both ranges, and a sum of five items can have both: [1,5] for each item and [5,25] for the sum.

- **Direct (`chosen`) bindings:** keep `allowed_range`. Validation stays strict, as it is now.
- **Derived bindings:** use `input_ranges` and `derived_range`. `input_ranges` is a map from column to [min, max], and each column is optional. `derived_range` is optional. The schema rejects `allowed_range` on a derived binding, so the ambiguous form cannot be written.

## Validator: scoped checks with statuses

Each range check returns one of `passed`, `failed`, `deferred` or `unresolved`.

- **At intake:** check `chosen.allowed_range` and `input_ranges` strictly.
- **`derived_range`:** always `deferred` at intake. The numerical reference stage checks it strictly after it has built the variable. Intake never runs the transformation.
- **Messages:** send structured facts only: field, column, declared range, and observed min and max. The repair model repeated the false conclusion because it was given a verdict. Give it the data and one narrow question.
- **Report:** state which ranges were checked at intake, which were deferred, and which were never checked.

## Extraction prompt

- **Example:** give one worked example. Five items scored 1–5 and summed get `input_ranges` of [1,5] for each item.
- **Rule:** include `derived_range` [5,25] only if the source states it. Do not guess a range, and do not compute one.

## Cached ambiguous bindings

1. Run one deterministic migration over the cache.
   - Each derived binding with an old `allowed_range` has that value moved to `unscoped_range`, with status `unresolved`.
   - The controller does not decide the scope and does not change the numbers.
   - A second run changes nothing, because already-migrated bindings no longer have `allowed_range`.
2. Send only the `unresolved` bindings to a targeted Sonnet repair.
   - **Input:** the transformation text, the source excerpt, the unscoped range, and the observed min and max for each input column.
   - **Question:** "Which scope does this range describe?"
   - **Allowed outputs:** `input_ranges`, `derived_range`, both, or drop. Each answer needs a supporting quote from the source. If no quote supports a scope, the binding stays `unresolved`.
3. All other cached extraction and contract output passes through untouched. Nothing is edited by hand.

## Keeping an unresolved repair from becoming "justified unavailable"

Enforce this in the controller, not in the prompt.

- **Evidence rule:** a verdict of "computation unavailable" must cite a check with status `failed`. That check must have a valid scope and a real observed violation.
- **Other statuses:** `unresolved` and `deferred` are separate end states. The report shows them as "binding not resolved" and "validated downstream". They are never merged into "data out of range".
- **Repair output:** limited by schema to `resolved` (scope plus quote) or `unresolved`. There is no free-text field in which the model can argue that the computation is unavailable.
- **Retry limit:** one Sonnet repair attempt per binding. If it fails, the binding stays `unresolved`. The run continues for the other variables, and the final report marks that variable as not validated.

## Cost

These changes add no work for a stronger model. They add one migration script, one schema change, a validator status type, and Sonnet calls only for the ambiguous cached bindings.
