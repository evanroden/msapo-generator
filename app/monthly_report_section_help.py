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
    "cover": SectionHelp("Check logos and cover", "Change cover details", "Choose the client logo, ENFRA logo and cover photo. The report month and contents list are rebuilt from your selections.", "Address or footer wording", "Cover artwork to keep", "Updated cover artwork"),
    "organization": SectionHelp("Check people and contacts", "Update people, contacts or workflows", "Check names, roles, reporting lines and facility contacts. Keep charts and outage procedures that are still correct. You can build an editable org chart from reviewed contacts in Site information.", "Organization and outage instructions", "Charts and outage workflows to keep", "Updated org chart or outage workflow"),
    "activity": SectionHelp("Review work and photos", "Update work, counts or photos", "Summarize work completed at each site this month. Keep only supported work-order counts; missing historical figures stay blank. Add current improvement photos and captions. Vendor-file findings can be added in This month’s work.", "Work completed this month", "Work and improvement pictures to keep", "New improvement photo"),
    "scorecards": SectionHelp("Check utilities and capacity", "Update utility results or capacity", "Add available utility results for the reporting period. Leave unknown capacity values blank; use a pending-results note only when its status is confirmed.", "Utility analysis or pending results", "Utility charts to keep", "Updated utility chart"),
    "mbcx": SectionHelp("Review commissioning results", "Update MBCx findings or pages", "Use this month’s monitoring or commissioning findings. Keep the standing ENFRA Connect explanation if it remains accurate, and add relevant MBCx pages in This month’s work.", "MBCx findings or standing explanation", "MBCx pages to keep", "Updated MBCx page image"),
    "maintenance": SectionHelp("Check service dates and pages", "Update service calls or vendor pages", "Keep service calls for the reporting month. Review each vendor page for work performed and findings. Leave out prices, legal terms and blank/signature-only pages. Add complete vendor files in This month’s work.", "Maintenance completed this month", "Vendor service pages to keep", "Updated service-page image"),
    "subcontractors": SectionHelp("Check vendor contacts and status", "Update vendors, contacts or MSA status", "Check the vendor, discipline, facility, contact details and agreement status. Keep unchanged rows. You can edit individual contact fields in Site information.", "Vendor status notes", "Vendor/contact pages to keep", "Updated vendor-contact page"),
    "water": SectionHelp("Check readings and follow-ups", "Update water-treatment pages or findings", "Check service dates, system names, readings, out-of-limit results and follow-ups. Keep relevant chemical/service pages only. Add this month’s water-treatment files in This month’s work; check the resulting activity wording.", "Water-treatment findings and follow-ups", "Water-treatment pages to keep", "Updated water-treatment page image"),
    "issues": SectionHelp("Review ongoing equipment issues", "Update issues or resolution status", "Check every carried-forward issue. Mark it ongoing, updated or resolved using evidence in This month’s work. Remove a resolved item only after explicitly choosing to do so.", "Equipment issues, actions and current status", "Equipment evidence pictures to keep", "Updated equipment-condition photo"),
    "capital": SectionHelp("Review renewal priorities", "Update priorities or equipment life", "Check equipment condition, replacement priority and known timing. Enter a year, month or date only when known. Carry forward valid items. Client-facing tables must contain no prices or costs.", "Capital renewal notes", "Equipment and renewal pictures to keep", "Updated renewal-item photo"),
    "proposals": SectionHelp("Check proposal status", "Update pending or declined items", "Update scope, vendor and the decision: Pending, Approved, Declined, On hold or Not confirmed. Keep alternative options in the description. Keep supporting work descriptions, and remove every price and commercial/legal-only page from client output.", "Proposal scope and status notes", "Price-free proposal pages to keep", "Updated price-free proposal image"),
    "training": SectionHelp("Review training already entered", "Update training, roles or known hours", "Record training that actually occurred, with topic, participants’ roles and hours only when known. Add relevant photos. Leave out empty example text and placeholder hours.", "Training completed, roles and known hours", "Training pictures to keep", "New training photo"),
    "rfi": SectionHelp("Check requested information", "Update requests or completion", "Check requested items by facility and mark only confirmed completions. Keep open requests visible.", "Requested-information notes", "Supporting request pages to keep", "Updated supporting picture"),
    "other": SectionHelp("Review this additional content", "Edit and place this content", "Check this content before choosing its section. Keep useful work from a partially finished report; leave decorative or irrelevant material in the preserved original.", "Additional report text", "Additional pictures/pages to keep", "Updated picture"),
}


def section_help(key):
    return SECTION_HELP.get(key, SECTION_HELP["other"])


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
