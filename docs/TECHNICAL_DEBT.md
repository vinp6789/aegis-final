# Technical Debt

## Phase 4 Statistical Dependencies

Phase 4 Leading Indicator Discovery currently uses self-contained NumPy-based statistical routines in `analytics/discovery/discovery_engine.py` because the available runtime did not include `statsmodels` or `scipy`.

### NumPy-Based Implementations

- `DiscoveryEngine.stationarity_test`
  - Implements an Augmented Dickey-Fuller-style stationarity check.
  - Uses NumPy least-squares regression and an approximate p-value calculation.
  - Applies first differencing when the raw series is not stationary.

- `DiscoveryEngine.johansen_cointegration_test`
  - Implements a Johansen-style cointegration proxy.
  - Uses NumPy least-squares residual stationarity rather than the full Johansen trace/eigenvalue procedure.

- `DiscoveryEngine.granger_causality_test`
  - Implements a Granger-style F-test.
  - Uses NumPy lag matrices, restricted/unrestricted least-squares models, residual sums of squares, and an approximate F survival calculation.

- `DiscoveryEngine.transfer_entropy`
  - Implements Shannon transfer entropy with NumPy quantile discretization.
  - This is acceptable as a local implementation, but should be benchmarked against a specialist information-theory implementation if one is later introduced.

### Recommended Future Replacements

- Replace the ADF proxy with `statsmodels.tsa.stattools.adfuller`.
- Replace the cointegration proxy with `statsmodels.tsa.vector_ar.vecm.coint_johansen`.
- Replace the Granger proxy with `statsmodels.tsa.stattools.grangercausalitytests` or an equivalent statsmodels OLS/F-test pipeline.
- Replace approximate F-test p-values with `scipy.stats.f.sf` if retaining the custom Granger implementation.
- Consider replacing or validating transfer entropy with a dedicated information-theory package, or keep the current implementation with expanded calibration tests.

### Interface Readiness

The current public result dataclasses are already structured enough for a later implementation swap:

- `StationarityResult`
- `CointegrationResult`
- `GrangerCausalityResult`
- `TransferEntropyResult`
- `HorizonEvaluation`

The calling lifecycle code consumes stable fields such as `granger.p_value` and `transfer_entropy.entropy`, so dependency-backed implementations can be introduced later without changing lifecycle state-transition interfaces.
