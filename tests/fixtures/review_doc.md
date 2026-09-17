# Vendor Onboarding Plan

**Owner:** Operations
**Status:** Draft for review
**Date:** September 2026

---

This plan describes how new vendors move from signed contract to first payment. It covers intake, checks, and handover to finance.

## 1. Intake

Vendors submit the intake form through the supplier portal. The form captures legal name, tax identifiers, and bank details for the payment_profile record.

| ID | Step | Owner | Priority |
|---|---|---|---|
| ON-101 | Collect intake form | Operations | High |
| ON-102 | Validate tax identifier | Finance | Medium |
| ON-103 | Create vendor record | Operations | Low |

## 2. Checks

### 2.1 Sanctions screening

Every vendor is screened against the consolidated sanctions list before activation. A match pauses onboarding until compliance clears it.

- Screening runs nightly for active vendors.
- New vendors are screened on submission.

### 2.2 Bank verification

Bank details are confirmed with a micro-deposit. The vendor confirms the amount within five business days.

<!-- TODO: confirm whether micro-deposits are allowed for vendors outside the US -->

## 3. Handover

Finance receives the approved record and schedules the first payment run. Files land in `app_inputs/runs/{business_date}/finance/vendor_handover_extract_with_long_name.csv`.

```yaml
handover:
  - owner: finance
  - sla_days: 2
```
