# Report interface checks

The common renderer was tested against the existing Petersen artifacts while the fresh runs were in progress. This checks the interface, not the new runs' scientific acceptance.

Chrome checks:
- Desktop layout: title, findings, section navigation, evidence table and grouped curves render; no CSS appears as page content.
- Search for “pupil”: 39 result records shown in the historical fixture.
- Phone viewport requested at 390 × 844: headings and section navigation wrap; document scroll width is 375 px, inside the 390 px viewport. Wide evidence tables scroll within their containers instead of widening the page.
- Temporary viewport override reset after inspection.

The final two reports still require checks against their own completed artifacts.

Additional navigation check: a direct link to #quantity-c017 opened the collapsed browser, entered c017 in the filter and showed exactly that one result row. The preview was reloaded with a cache-busting query to verify the current rendered file.
