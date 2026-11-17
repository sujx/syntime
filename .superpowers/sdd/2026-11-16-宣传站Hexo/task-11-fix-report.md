# Task 11 Fix Report

## Changes

### I1. Section attribute order finalized (constraint 8)

**File:** `website/themes/syntime/layout/index.ejs`

Three `<section>` elements with anchor ids had `class` before `id`, violating global constraint 8 ("带锚点 id 的 `<section>` 一律 `id` 写在 `class` 之前"). Fixed by swapping attribute order:

- Line 141: `<section class="sec dark-sec" id="quickstart">` → `<section id="quickstart" class="sec dark-sec">`
- Line 182: `<section class="sec" id="about">` → `<section id="about" class="sec">`
- Line 206: `<section class="sec sec-gray" id="faq">` → `<section id="faq" class="sec sec-gray">`

### I2. Skip link JS scroll behavior (ruling R-4)

**File:** `website/source/js/main.js`

Added a click handler on `.skip` links at the end of the IIFE (before closing `})();`). The handler:

1. Calls `e.preventDefault()` to override native anchor scrolling.
2. Uses `window.scrollTo({ top: mainEl.offsetTop, behavior: 'instant' })` per R-4.
3. Sets `tabindex="-1"` on `#main` and focuses it (without scrolling) so keyboard users land in the main content.
4. Is null-safe: the handler is only registered when both `.skip` and `#main` exist in the DOM.

## Gate Commands

### Hexo generate (ERROR/WARN/FATAL count)

```
$ npx hexo clean && npx hexo generate 2>&1 | grep -Ec 'ERROR|WARN|FATAL'
0
```

### Node tests

```
$ node --test tests/
ℹ tests 83
ℹ suites 0
ℹ pass 83
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 440.07885
```

## Concerns

None. Both fixes are minimal and surgical. The skip link handler follows the existing null-safe pattern used throughout `main.js` (e.g., `seg`, `banner` guards). All 83 existing tests continue to pass, including the T11 skip-link structural test.
