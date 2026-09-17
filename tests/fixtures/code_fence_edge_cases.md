# Test PRD Document

## 1. Overview
This is a PRD with **ten deterministic detections** we need to preserve exactly.

**Key Inputs:**
| Input | Source |
|-------|--------|
| Claim ID | EDI 837 |
| NPI | Provider Master |

**Steps to reproduce:**
- Step one
- Step two
- Step three

## 2. Example Payload
Here is an example API response, including a comment a developer might leave in example HTML:

```html
<!-- this comment lives INSIDE a code fence and should NOT be extracted -->
<div class="row">
  <span>value</span>
</div>
```

And here's an example of table syntax we document for contributors (this is illustrative text inside a code fence, not a real table):

```
| Column A | Column B |
|----------|----------|
| foo      | bar      |
```

## 3. Numbering Note
3. This sentence happens to start with a digit and a period as prose, not a list item, so it should not be flagged as broken markdown.

## Open questions
<!-- TODO: confirm whether K3 detection threshold is 0.8 or 0.85 -->
<!-- reviewer note: this needs legal sign-off before ship -->

> First quoted concern about data retention.

> Second quoted concern about SLA terms.

## Ordered list starting point
5. Fifth item
6. Sixth item
7. Seventh item
