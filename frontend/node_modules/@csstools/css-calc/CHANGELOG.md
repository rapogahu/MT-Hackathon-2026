# Changes to CSS Calc

### 3.4.1

_September 25, 2026_

- Improve performance and avoid a stack overflow when solving deeply nested calculations
- Throw when a math function exceeds the maximum number of nodes
- Fixed `tan()` at asymptote values beyond the first period (`270deg`, `-270deg`, ...) to match the specification
- Fixed `round(line-width, ...)` to choose the non-zero candidate multiple when `A` is negative
- Fixed `round(down/up, ...)` with a negative step to choose the correct candidate multiple
- Fixed `log(A, 0)` to return `NaN` as specified (only `B` values between 0 and 1, or greater than 1, are valid)
- Fixed `log(1, B)` to return `0⁺` as specified, except when `B` is `NaN` (NaN stays infectious, so `log(1, NaN)` is now `NaN`)
- Fixed `random()` to not mutate the caller's `options` object
- Fixed `random(fixed <number>, ...)` to clamp the value to the highest representable value less than 1
- Fixed `random()` to treat `max < min` as `max = min` instead of swapping the arguments
- Fixed `random()` to not return an unreachable `max` when a `step` is given
- Fixed `random()` to return `A` (the minimum) when `A` is infinite, instead of `NaN`
- Fix infectious `NaN`
- Fixed the `precision` option to not round values that serialize in scientific notation
  (e.g. `calc(1e-10 * 1e-10)` was rounded to `0`, it is now left untouched)
- Fixed `random()` to not round values that serialize in scientific notation
  (e.g. `random(fixed 0.5, 1e-20, 1e-10)` returned `0`)
- Updated [`@csstools/css-tokenizer`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-tokenizer) to [`4.0.1`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-tokenizer/CHANGELOG.md#401) (patch)
- Updated [`@csstools/css-tokenizer`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-tokenizer) to [`4.0.2`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-tokenizer/CHANGELOG.md#402) (patch)
- Updated [`@csstools/css-parser-algorithms`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-parser-algorithms) to [`4.0.1`](https://github.com/csstools/postcss-plugins/tree/main/packages/css-parser-algorithms/CHANGELOG.md#401) (patch)

[Full CHANGELOG](https://github.com/csstools/postcss-plugins/tree/main/packages/css-calc/CHANGELOG.md)
