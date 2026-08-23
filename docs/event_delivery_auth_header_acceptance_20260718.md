# DeliveryOutbox Authentication Header Acceptance

P8 adds the same optional token-header contract used by
`FallEventReporterService`. In post mode, DeliveryOutbox sends
`{MAIN_SYSTEM_ALERT_TOKEN_HEADER: MAIN_SYSTEM_ALERT_TOKEN}` only when both
values are non-empty after trimming. Otherwise it sends no `headers` argument.

The delivery payload JSON is unchanged. Defaults remain delivery-disabled and
no real target or `.env` was used. The test intercepts `requests.post` and
verifies all four header/token combinations plus a 200 `sent` result.
