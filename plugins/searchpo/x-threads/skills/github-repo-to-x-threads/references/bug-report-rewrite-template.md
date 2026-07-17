# Professional Bug Report Rewrite Template

Use this when the input is a KYC/support/platform complaint, especially when the
draft contains anger, hashtags, repeated mentions, all-caps, or a ticket number.

## Main Rule

Do not publish a customer-support rant on the main Agent engineering account.
Either:

- rewrite it as a cold PRD-style bug report, or
- move it to a small account/private support channel, or
- tie it to an Agent workflow reliability lesson with a concrete mechanism.

## Template

```text
Bug Report · <product/vendor>

Repro:
1. <step>
2. <step>
3. <observed failure>

Impact:
<who is blocked, what legitimate workflow fails, and why this matters>

Expected:
<specific product behavior or manual review path>

Evidence:
<screenshots/ticket id are attached or available privately>

Question:
Has anyone designed a safer appeal/manual-review path for this class of KYC/UI failure?
```

## Remove

- rage words, insults, and all-caps;
- hashtag stacks;
- repeated `@company` tagging;
- demands like `fix this bug now`;
- unsupported accusations about motive.

## Main-Account Variant

Only use the main account if the post teaches an Agent systems lesson:

```text
Real KYC failure mode today:
the UI locked a field after save, then the verifier rejected the same field as missing.

Agent workflow lesson: validation state is part of the task environment.
If the system cannot reopen, appeal, or escalate, a small UI bug becomes a terminal failure.

Checklist:
1. editable saved fields
2. explicit validation trace
3. appeal/manual-review path
4. user-visible state diff

What would you log so a human reviewer can audit the failure?
```
