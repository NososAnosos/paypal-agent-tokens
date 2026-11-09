"""Injection / scope-attack cases as DATA (DEMO beat 4).

Adding a case means editing only this module — the runner in test_injection.py
is case-agnostic. Each case: free-action reports + propose + ordered capture
attempts with expected blocked reason or CAPTURED.
"""

# Canonical DEMO beat 4: YOLO envelope on skyair; poisoned review drives MegaMart TV;
# scope rejection must not burn the token; in-scope flight still captures.
BEAT4_YOLO_TV = {
    "name": "beat4_yolo_tv_injection",
    "reports": [
        {"action": "search_flights", "detail": "SFO to JFK under $400"},
        {"action": "read_reviews", "detail": "UA1234"},
    ],
    "propose": {
        "mode": "yolo",
        "payee_id": "skyair",
        "amount": "400.00",
        "description": "best flight under $400",
    },
    "captures": [
        {
            "payee_id": "megamart",
            "amount": "900.00",
            "expect": {"blocked": "payee_out_of_scope"},
        },
        {
            "payee_id": "skyair",
            "amount": "340.00",
            "expect": {"state": "CAPTURED"},
        },
    ],
}

# Ceiling holds independently of payee: inflated skyair amount inside same envelope.
YOLO_AMOUNT_OVER_CEILING = {
    "name": "yolo_amount_over_ceiling",
    "reports": [
        {"action": "search_flights", "detail": "SFO to JFK under $400"},
    ],
    "propose": {
        "mode": "yolo",
        "payee_id": "skyair",
        "amount": "400.00",
        "description": "best flight under $400",
    },
    "captures": [
        {
            "payee_id": "skyair",
            "amount": "460.00",
            "expect": {"blocked": "amount_over_ceiling"},
        },
        {
            "payee_id": "skyair",
            "amount": "340.00",
            "expect": {"state": "CAPTURED"},
        },
    ],
}

# Verify mode: any amount other than the exact approved figure is refused.
VERIFY_AMOUNT_NOT_EXACT = {
    "name": "verify_amount_not_exact",
    "reports": [
        {"action": "search_flights", "detail": "UA1234"},
    ],
    "propose": {
        "mode": "verify",
        "payee_id": "skyair",
        "amount": "340.00",
        "description": "United 1234",
    },
    "captures": [
        {
            "payee_id": "skyair",
            "amount": "341.00",
            "expect": {"blocked": "amount_not_exact"},
        },
        {
            "payee_id": "skyair",
            "amount": "340.00",
            "expect": {"state": "CAPTURED"},
        },
    ],
}

CASES = [BEAT4_YOLO_TV, YOLO_AMOUNT_OVER_CEILING, VERIFY_AMOUNT_NOT_EXACT]
