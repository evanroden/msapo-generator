"""Section-specific language for asset managers, shared by setup and editing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionHelp:
    keep: str
    edit: str
    guidance: str
    text_label: str
    picture_label: str
    upload_label: str


SECTION_HELP = {
    "cover": SectionHelp("Review the cover", "Change cover details", "Saved branding and the original ENFRA cover design are used automatically. Change the photograph only when needed; the reporting month comes from your selection above.", "Address or footer wording", "Cover artwork to keep", "Updated cover artwork"),
    "organization": SectionHelp("Check people and contacts", "Update people, contacts or workflows", "Update the team chart, facility contacts or outage procedures where details changed.", "Organization and outage instructions", "Charts and outage workflows to keep", "Updated org chart or outage workflow"),
    "activity": SectionHelp("Review work and photos", "Update work, counts or photos", "Add this month’s work files or write a summary below.", "Work completed this month", "Work and improvement pictures to keep", "New improvement photo"),
    "scorecards": SectionHelp("Check utilities and capacity", "Update utility results or capacity", "Add this month’s utility results. Leave unknown capacity values blank or NR; use a pending-results note only when confirmed.", "Utility analysis or pending results", "Utility charts to keep", "Updated utility chart"),
    "mbcx": SectionHelp("Review commissioning results", "Update MBCx findings or pages", "Add monitoring results or a brief status update.", "MBCx findings or standing explanation", "MBCx pages to keep", "Updated MBCx page image"),
    "maintenance": SectionHelp("Check ENFRA onsite service calls", "Update calls performed by onsite ENFRA technicians", "ENFRA technicians onsite only. Add vendor reports in [Monthly Activity Summary](#report-section-activity).", "Maintenance completed this month", "Vendor service pages to keep", "Updated service-page image"),
    "subcontractors": SectionHelp("Check vendor contacts and status", "Update vendors, contacts or MSA status", "Update vendor contacts or agreement status.", "Vendor status notes", "Vendor/contact pages to keep", "Updated vendor-contact page"),
    "water": SectionHelp("Check readings and follow-ups", "Update water-treatment pages or findings", "Add this month’s water-treatment reports. Check readings that are out of range and any follow-up work.", "Water-treatment findings and follow-ups", "Water-treatment pages to keep", "Updated water-treatment page image"),
    "issues": SectionHelp("Review ongoing equipment issues", "Update issues or resolution status", "Update open equipment issues, actions and status. Remove an item from this report only when deliberately chosen.", "Equipment issues, actions and current status", "Equipment evidence pictures to keep", "Updated equipment-condition photo"),
    "capital": SectionHelp("Review renewal priorities", "Update priorities or equipment life", "Update replacement priorities and expected timing. Leave unknown dates blank.", "Capital renewal notes", "Equipment and renewal pictures to keep", "Updated renewal-item photo"),
    "proposals": SectionHelp("Check proposal status", "Update proposal scope or decision", "Update scope, vendor and decision. Client output must exclude prices and commercial or legal-only pages.", "Proposal scope and status notes", "Price-free proposal pages to keep", "Updated price-free proposal image"),
    "training": SectionHelp("Review training already entered", "Update training, roles or known hours", "Hospital/client staff training.", "Training completed, roles and known hours", "Training pictures to keep", "New training photo"),
    "rfi": SectionHelp("Check requested information", "Update requests or completion", "Track requests by facility and status. Mark a response complete only when confirmed.", "Requested-information notes", "Supporting request pages to keep", "Updated supporting picture"),
    "other": SectionHelp("Review this additional content", "Edit and place this content", "Check this content before choosing its section. Keep useful work from a partially finished report; leave decorative or irrelevant material in the preserved original.", "Additional report text", "Additional pictures/pages to keep", "Updated picture"),
}



# The importer keeps the full guidance above. In the routine editor, show
# just the context needed to make an informed choice without repeating field
# labels. Blank hints mean the nearby native editor is self-explanatory.
_EDITOR_GUIDANCE = {
    "cover": "Include the report month, selected sites and approved cover details. Provide changes only if needed. Fictional example: a current-month facility photograph.",
    "organization": "Include the current org chart, contacts and outage procedures. Provide changed roles or diagrams. Fictional example: an updated after-hours escalation route.",
    "activity": "Include completed work, findings and unresolved work, not assumptions. Provide work orders, vendor reports or your own notes. Fictional example: inspected a test pump; repair pending.",
    "scorecards": "Include verified utility results and capacity. Provide readings or a confirmed pending-results note; leave unknown values blank. Fictional example: a test meter reading.",
    "mbcx": "MBCx means monitoring-based commissioning. Provide verified monitoring results or a status update. Fictional example: a test trend showed an open control issue.",
    "maintenance": "Include ENFRA onsite technician service calls only, not vendor work. Provide call date, asset and outcome. Fictional example: checked a test valve.",
    "subcontractors": "Include vendor agreement and contact status. Provide only confirmed changes. Fictional example: a sample service agreement is awaiting renewal.",
    "water": "Include treatment readings and follow-ups. Provide the treatment report and verified exceptions. Fictional example: a sample reading requires retesting.",
    "issues": "Include unresolved equipment issues, actions and current status. Provide evidence and corrections. Fictional example: a test pump seal remains under review.",
    "capital": "Include replacement priorities and expected timing. Provide confirmed asset needs; leave unknown dates blank. Fictional example: review a test chiller next year.",
    "proposals": "Include proposal scope and decision status. Provide verified status and approved source evidence; do not copy vendor-invoice amounts. Fictional example: test valve replacement proposed.",
    "training": "Include completed hospital/client staff training. Provide topic, roles and confirmed hours. Fictional example: a sample safety session completed.",
    "rfi": "RFI means request for information. Provide each request and confirmed response status. Fictional example: a sample drawing request remains open.",
    "accounts_receivable": "Include source-verified receivable status only where approved for this report. Provide the reviewed ledger and audience decision. Fictional example: a sample invoice is awaiting review.",
    "other": "Include additional relevant information only where it belongs. Provide a clear description and source. Fictional example: a test facility update awaiting verification.",
}

_EDITOR_HEADING_HELP = {
    "mbcx": "MBCx means monitoring-based commissioning. Include only verified findings.",
}


def editor_section_heading_help(key):
    """Explain an unfamiliar acronym at its existing heading, without extra captions."""
    return _EDITOR_HEADING_HELP.get(key)


def editor_section_guidance(key):
    """Compact, nonblocking hints for the ordinary Monthly editor."""
    if key in _EDITOR_GUIDANCE:
        return _EDITOR_GUIDANCE[key]
    return section_help(key).guidance


def section_help(key):
    return SECTION_HELP.get(key, SECTION_HELP["other"])


def editor_section_title(section):
    """Plain editor names leave the pinned design's exported headings intact."""
    return {"proposals": "Proposals", "rfi": "Information requests (RFI)"}.get(section.key, section.title)


def update_label(key):
    return {
        "business_hours_workflow": "Change the business-hours outage procedure",
        "after_hours_workflow": "Change the after-hours outage procedure",
        "thermal_capacity": "Update thermal capacity or units",
        "utility_analysis": "Update utility analysis or the pending-results note",
        "capital_renewal": "Update renewal priorities",
        "end_of_life": "Update equipment useful-life dates",
        "proposals": "Update proposal scope or status",
        "rfi_matrix": "Update requested items or completion",
        "mbcx_report": "Update commissioning findings or pages",
    }.get(key, "Update " + key.replace("_", " "))
