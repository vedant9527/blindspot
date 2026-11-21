# Blindspot Evaluation Results

**Held-out manifest SHA-256:** `816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`

| System | Injected Caught | hide_focus | keyboard_trap | covering_banner | positive_tabindex | label_mismatch | W3C Clean False Flags | Median s/page | Gemini Calls/page | Est. Cost/page |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `axe` | **5/12** | 0/3 | 0/3 | 0/1 | 2/2 | 3/3 | 10 (4p) | 6.2s | 0.0 | \$0.0000 |
| `single_gemini` | **0/13** | 0/3 | 0/3 | 0/1 | 0/3 | 0/3 | 0 (4p) | 12.1s | 1.0 | \$0.0022 |
| `code_only` | **10/13** | 2/3 | 2/3 | 1/1 | 3/3 | 2/3 | 0 (4p) | 27.7s | 0.0 | \$0.0000 |
| `blindspot` | **12/13** | 3/3 | 2/3 | 1/1 | 3/3 | 3/3 | 0 (4p) | 32.6s | 73.8 | \$0.0362 |

## GOV.UK Accessibility Audit Page (Keyboard & Focus Cases)

- `axe`: 22 confirmed/reported
- `single_gemini`: 2 confirmed/reported
- `code_only`: 1 confirmed/reported
- `blindspot`: 8 confirmed/reported

## Dropped / Blocked Pages (Not Counted as Caught or Missed)

| Set | URL | Reason | Affected |
| --- | --- | --- | --- |
| `heldout` | https://carbonhealth.com/ | bot check (challenge widget) | manifest_preflight |
| `heldout` | https://www.ticketmaster.com/ | bot check (challenge widget) | manifest_preflight |
| `heldout` | https://headway.co/ | HTTP 403 | axe, single_gemini, code_only, blindspot |
| `heldout` | https://asktia.com/ | RuntimeError: No visible tabbable elements found on https://asktia.com/ to inject positive_tabindex | axe |
