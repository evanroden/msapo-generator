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
    "activity": SectionHelp("Review work and photos", "Update work, counts or photos", "Add this month’s work files or write a summary below. Review counts and evidence before including them.", "Work completed this month", "Work and improvement pictures to keep", "New improvement photo"),
    "scorecards": SectionHelp("Check utilities and capacity", "Update utility results or capacity", "Add this month’s utility results. Leave unknown capacity values blank or NR; use a pending-results note only when confirmed.", "Utility analysis or pending results", "Utility charts to keep", "Updated utility chart"),
    "mbcx": SectionHelp("Review commissioning results", "Update MBCx findings or pages", "MBCx means monitoring-based commissioning: using equipment performance data to review operating issues and improvements. ENFRA Connect is the reporting platform named in the existing design. Add only verified results from monitoring that has started; otherwise describe the current status without inventing findings or savings.", "MBCx findings or standing explanation", "MBCx pages to keep", "Updated MBCx page image"),
    "maintenance": SectionHelp("Check ENFRA onsite service calls", "Update calls performed by onsite ENFRA technicians", "ENFRA technicians onsite only. Add vendor reports in [Monthly Activity Summary](#report-section-activity).", "Maintenance completed this month", "Vendor service pages to keep", "Updated service-page image"),
    "subcontractors": SectionHelp("Check vendor contacts and status", "Update vendors, contacts or MSA status", "Update vendor contacts or agreement status.", "Vendor status notes", "Vendor/contact pages to keep", "Updated vendor-contact page"),
    "water": SectionHelp("Check readings and follow-ups", "Update water-treatment pages or findings", "Add this month’s water-treatment reports. Check readings that are out of range and any follow-up work.", "Water-treatment findings and follow-ups", "Water-treatment pages to keep", "Updated water-treatment page image"),
    "issues": SectionHelp("Review ongoing equipment issues", "Update issues or resolution status", "Update open equipment issues, actions and status. Remove an item from this report only when deliberately chosen.", "Equipment issues, actions and current status", "Equipment evidence pictures to keep", "Updated equipment-condition photo"),
    "capital": SectionHelp("Review renewal priorities", "Update priorities or equipment life", "Update replacement priorities and expected timing. Leave unknown dates blank.", "Capital renewal notes", "Equipment and renewal pictures to keep", "Updated renewal-item photo"),
    "proposals": SectionHelp("Check proposal status", "Update proposal scope or decision", "Update scope, vendor and decision. Client output must exclude prices and commercial or legal-only pages.", "Proposal scope and status notes", "Price-free proposal pages to keep", "Updated price-free proposal image"),
    "training": SectionHelp("Review training already entered", "Update training, roles or known hours", "This section covers hospital or client staff training, not ENFRA’s internal employee training. Update the standing staff matrix, then record training confirmed complete this month, including its date, participants, method and hours only when known.", "Training completed, roles and known hours", "Training pictures to keep", "New training photo"),
    "rfi": SectionHelp("Check requested information", "Update requests or completion", "Track requests by facility and status. Mark a response complete only when confirmed.", "Requested-information notes", "Supporting request pages to keep", "Updated supporting picture"),
    "other": SectionHelp("Review this additional content", "Edit and place this content", "Check this content before choosing its section. Keep useful work from a partially finished report; leave decorative or irrelevant material in the preserved original.", "Additional report text", "Additional pictures/pages to keep", "Updated picture"),
}


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
