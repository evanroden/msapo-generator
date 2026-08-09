from app.workflow_review import (
    ReviewNeeds,
    email_is_valid_or_blank,
    retain_review_needs,
    review_needs,
    tax_alert_message,
)


def _complete_needs(**overrides):
    values = {
        "routing_ready": True,
        "request_type": "PO",
        "original_po_number": "",
        "job_number": "RRH-695400022-O&M",
        "asset_resolved": True,
        "total": "$1,250.00",
        "vendor": "Vendor",
        "description": "Pump Repair",
        "contact_email": "",
    }
    values.update(overrides)
    return review_needs(**values)


def test_tax_alert_is_absent_only_when_tax_is_included():
    assert tax_alert_message("included") == ""
    assert "not included" in tax_alert_message("excluded")
    assert "No tax was found" in tax_alert_message("unclear")
    assert "No tax was found" in tax_alert_message(None)


def test_complete_guesses_leave_no_visible_exception_questions():
    needs = _complete_needs()

    assert not needs.any
    assert not any(
        (
            needs.routing,
            needs.original_po_number,
            needs.job_number,
            needs.asset,
            needs.total,
            needs.vendor,
            needs.description,
            needs.contact_email,
        )
    )


def test_unresolved_or_invalid_values_are_moved_out_of_corrections():
    needs = _complete_needs(
        routing_ready=False,
        request_type="CHANGE ORDER",
        original_po_number="",
        job_number="",
        asset_resolved=False,
        total="$0.00",
        vendor="",
        description="",
        contact_email="not-an-email",
    )

    assert needs.any
    assert needs.routing
    assert needs.original_po_number
    assert needs.job_number
    assert needs.asset
    assert needs.total
    assert needs.vendor
    assert needs.description
    assert needs.contact_email


def test_optional_email_accepts_blank_and_rejects_malformed_values():
    assert email_is_valid_or_blank("")
    assert email_is_valid_or_blank("manager@example.com")
    assert not email_is_valid_or_blank("manager@example")


def test_review_questions_stay_visible_and_accumulate_new_dependency_gaps():
    previous = ReviewNeeds(
        routing=True,
        original_po_number=False,
        job_number=True,
        asset=False,
        total=True,
        vendor=False,
        description=False,
        contact_email=False,
    )
    current = ReviewNeeds(
        routing=False,
        original_po_number=False,
        job_number=False,
        asset=True,
        total=False,
        vendor=False,
        description=False,
        contact_email=False,
    )

    retained = retain_review_needs(previous, current)

    assert retained.routing
    assert retained.job_number
    assert retained.total
    assert retained.asset
    assert not retained.vendor
