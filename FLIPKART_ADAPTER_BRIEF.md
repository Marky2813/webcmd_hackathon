# Build Brief: Flipkart Search Adapter for webcmd

**Hand this entire file to your coding agent.** It is self-contained — context, verified recon, the exact interface contract, and acceptance criteria.

---

## 0. TL;DR for the agent

Build a **webcmd plugin** exposing a single command, `flipkart/search`, that searches Flipkart India and returns structured product results as JSON.

The output shape is **not negotiable** — it must mirror the existing `amazon-in/search` adapter exactly, because a separate Python application merges results from both into one ranked list. Column names and types are a hard contract (Section 4).

If the `webcmd-adapter-author` skill is available on this machine, **load it** — it drives adapter authoring end-to-end (recon → field decoding → adapter code → verify). If not, follow `webcmd-usage` first for orientation.

---

## 1. Context — what this feeds

This adapter is one component of a 3-hour hackathon project: a **Telegram shopping assistant**. A user onboards once (name, shoe size, clothing size, budget ceiling, brand preferences), then chats naturally — *"need running shoes under 6k"*. An agent searches multiple shopping sites in parallel, merges and ranks results against the stored profile, and returns a personalized comparison.

Two things follow from this that affect your design:

1. **Results from different sites get compared numerically.** Prices must be parsed to numbers in the adapter. A string `"₹1,999"` breaks the merge.
2. **It is latency-sensitive.** The command is called live while a Telegram user waits. Budget: **under 25s hard, under 10s strongly preferred.** Prefer a faster strategy (PUBLIC / INTERCEPT) over browser-driven UI automation if a viable one exists.

The main app already works without you — it ships with Amazon.in and Myntra providers. **This adapter is additive.** Nothing is blocked on it, so favour correctness and a clean interface over speed of delivery. If you can only get some fields reliably, ship with the optional ones empty rather than guessing.

---

## 2. Preflight — do this first

```bash
webcmd --version     # expect >= 0.5.3
webcmd doctor        # daemon + runtime must be green
```

**Critical:** install esbuild globally before writing or installing any plugin.

```bash
npm i -g esbuild
```

Without it, `webcmd plugin install` prints:

```
⚠ esbuild not found. TS plugin files will not be transpiled and may fail to load.
```

…then installs anyway and **fails silently at runtime**. This was hit on the target machine already. Don't skip it.

---

## 3. Verified recon (already done — don't redo it)

These facts were confirmed live against Flipkart. Use them as a starting point, but **re-verify before relying on them** — the site changes.

**No Flipkart plugin exists in the webcmd registry.** `webcmd plugin search flipkart -f json` returns `{"plugins": [], "errors": []}`. The registry has ~130 plugins; the only shopping ones are `amazon`, `amazon-in`, `coupang`, `bigbasket`, `blinkit`, `zepto`. You are building this from scratch.

**Flipkart search is reachable and not hard bot-walled.** A generic browser fetch of:

```
https://www.flipkart.com/search?q=running+shoes
```

returned a full 61.7 KB result page containing **125 product links** (`/p/itm...`).

**The listing structure is highly regular.** Each product renders as a title link immediately followed by a price link sharing the same URL:

```markdown
[MIKE (N) Running Shoes For Men](https://www.flipkart.com/campus-mike-n-running-shoes-men/p/itm27c989f1e20c6?pid=SHOG4G3XXA5GHCY7&lid=...&marketplace=FLIPKART&q=running+shoes)
[

₹639

₹1,999

68% off

](https://www.flipkart.com/campus-mike-n-running-shoes-men/p/itm27c989f1e20c6?pid=SHOG4G3XXA5GHCY7&lid=...)
```

Notes on that sample:
- The shared URL is the natural join key for pairing title with price.
- `pid=SHOG4G3XXA5GHCY7` is the stable product ID → use it for `product_id`.
- Brand is embedded in the URL slug (`campus-mike-n-...`) and often absent from the visible title.
- **Sizes did not appear on the search listing.** Expect `sizes` to come back empty; that is acceptable (see Section 4).
- If you parse rendered markdown, **read as UTF-8 explicitly.** On Windows the ₹ sign arrives as mojibake (`â‚¹`) under the default cp1252 codepage.

The URL also accepts native filter params worth investigating for price bounds, e.g. `&p[]=facets.price_range.from=500` — pushing filtering into the URL beats post-filtering.

---

## 4. THE CONTRACT — must match exactly

Command name: **`flipkart/search`**. Access: `read`. Must work **logged out** — no login, no cookies required.

### Args

Names must match exactly; they mirror `amazon-in/search`.

| arg | type | required | notes |
|---|---|---|---|
| `query` | string | yes | **positional** |
| `--min-price` | number | no | INR, inclusive |
| `--max-price` | number | no | INR, inclusive |
| `--limit` | int | no | default `20`, range 1–50 |

### Columns

| column | type | required | notes |
|---|---|---|---|
| `rank` | int | yes | 1-based position in results |
| `product_id` | string | yes | the `pid=` value, e.g. `SHOG4G3XXA5GHCY7` |
| `title` | string | yes | |
| `brand` | string | no | empty string `""` if not extractable |
| `price` | **number** | yes | `639` — **not** `"₹639"`, no symbol, no commas |
| `mrp` | **number** | yes | same rules; if no discount shown, set equal to `price` |
| `rating` | number | no | `null` if absent |
| `review_count` | int | no | `0` if absent |
| `sizes` | string | no | comma-separated, e.g. `"UK7,UK8,UK9"`; `""` if unavailable |
| `product_url` | string | yes | full absolute `https://www.flipkart.com/...` URL |
| `is_sponsored` | boolean | yes | `false` if undeterminable |

### The one rule that matters most

**Parse prices to numbers inside the adapter.** The consuming app does arithmetic across sites (budget filtering, discount comparison, cross-site ranking). Strings break it. This is the single most likely integration failure.

### Reference implementation to mirror

`amazon-in/search` is the model. Its real output, captured live:

```json
[
  {
    "rank": 1,
    "asin": "B0FFTD9NS8",
    "title": "Nike Mens Downshifter 14 Running Shoes",
    "price": 4160,
    "mrp": 4895,
    "rating": 4.5,
    "review_count": 220,
    "image_url": "https://m.media-amazon.com/images/I/51JjqvF1yrL._AC_UL320_.jpg",
    "product_url": "https://www.amazon.in/dp/B0FFTD9NS8",
    "is_sponsored": true
  }
]
```

Note `price` and `mrp` are bare integers. Match that. (`asin` is Amazon-specific — its equivalent here is `product_id`.)

If you can also return `image_url`, include it — it's a bonus, not required.

---

## 5. Constraints and non-goals

**Build only search.** Do not build login, cart, wishlist, or checkout commands. The consuming app has a hard rule that it never completes a payment, and the smallest possible write surface is deliberate. This adapter should be **read-only**.

- No authentication. Search must work for a logged-out user.
- No writes of any kind.
- Don't add commands beyond `flipkart/search`.
- Respect `--limit`; don't paginate beyond what's asked.
- Handle "no results" as an **empty array with exit code 0**, not an error.
- Fail loudly on a bot wall — a clear error beats silently returning nothing, so the caller can degrade gracefully.

---

## 6. Acceptance criteria

Ship when all of these pass:

```bash
# 1. Command registers with the correct interface
webcmd list -f json
#    → flipkart/search present, args and columns match Section 4 exactly

# 2. Basic search returns results
webcmd flipkart search "running shoes" --limit 5 -f json

# 3. Price bounds are respected — every returned price must be <= 6000
webcmd flipkart search "running shoes" --max-price 6000 --limit 10 -f json

# 4. Both bounds
webcmd flipkart search "t shirt" --min-price 500 --max-price 1500 --limit 5 -f json

# 5. A query with no plausible results exits 0 with []
webcmd flipkart search "asdkjhasdkjh" -f json
```

Manual checks:
- `price` and `mrp` are **JSON numbers**, not strings — check the raw JSON, not a formatted table
- `product_url` values open the correct product in a browser
- `rank` starts at 1 and increments
- Two consecutive runs return broadly consistent results
- End-to-end wall time is under 25s

---

## 7. Delivery

**Ship as a git repository**, installable directly:

```bash
webcmd plugin install github:<your-user>/<your-repo>
```

This is much smoother than sending a folder or zip. Include a short README with the install line and one example invocation.

Then send back:
1. The install command
2. The raw JSON output of `webcmd flipkart search "running shoes" --max-price 6000 --limit 5 -f json`
3. Any field you could **not** populate, and why

Item 3 matters — the consuming side has a wrapper written against this contract, and knowing which fields come back empty saves debugging time during integration.

---

## 8. If Flipkart fights back

If you hit a bot wall or a CAPTCHA:

- Try a different strategy tier — if UI automation is blocked, look for an intercept-able internal JSON endpoint; if a public endpoint is blocked, fall back to browser-driven UI.
- The generic `web` plugin's `fetch-browser` command reached Flipkart successfully today, which proves the page is obtainable through a real browser context. Worst case, the adapter can drive a browser and parse rendered output.
- The `webcmd-autofix` skill exists specifically for diagnosing failing webcmd commands — load it if you get stuck.

**Do not burn unlimited time on this.** It's a hackathon add-on and the main app ships without it. If Flipkart proves genuinely hostile, report back with what you found rather than grinding — that's a useful result too.
