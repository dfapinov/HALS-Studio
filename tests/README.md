# Test scope

Tests should catch a result or behaviour that would matter to someone using
Studio. Keep coverage for:

- Numerical correctness, physical conventions, units and invalid inputs.
- File compatibility, saved settings, migration and protection against data loss.
- Processing, cancellation, worker use and avoiding stale results.
- User actions such as selecting a trace, editing an origin, changing settings
  and reopening a project.
- Plot correctness: displayed data, scales, missing coverage and readable traces.

Avoid freezing labels, help text, colours, fonts, widget positions, default view
arrangements or the number of internal algorithm steps. If a presentation detail
has a functional consequence, test that consequence instead. For example, check
that a legend avoids a trace rather than requiring a particular search grid.

Use small, explicit fixtures for documents and files so adding bundled content
does not break unrelated tests. Mock external work or side effects when needed;
exercise real numerical and application code wherever practical. Parameterize
distinct cases and boundaries rather than every combination of equivalent UI
options.

When a test fails after an intentional change, first check whether it still
protects useful behaviour. Do not update an expected value merely to make it pass.
