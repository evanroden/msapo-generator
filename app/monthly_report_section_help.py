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
    "organization": SectionHelp("Check people and contacts", "Update people, contacts or workflows", "Check names, roles, reporting lines and facility contacts. Keep charts and outage procedures that are still correct. You can build an editable org chart from reviewed contacts in this section.", "Organization and outage instructions", "Charts and outage workflows to keep", "Updated org chart or outage workflow"),
    "activity": SectionHelp("Review work and photos", "Update work, counts or photos", "Summarize work completed at each site this month. Keep only supported work-order counts; missing historical figures stay blank. Add current improvement photos and captions. Upload supporting work files here; the tool drafts the first summary for you to edit.", "Work completed this month", "Work and improvement pictures to keep", "New improvement photo"),
    "scorecards": SectionHelp("Check utilities and capacity", "Update utility results or capacity", "Add available utility results for the reporting period. Leave unknown capacity values blank; use a pending-results note only when its status is confirmed.", "Utility analysis or pending results", "Utility charts to keep", "Updated utility chart"),
    "mbcx": SectionHelp("Review commissioning results", "Update MBCx findings or pages", "Use this month’s monitoring or commissioning findings. Keep the standing ENFRA Connect explanation if it remains accurate, and add relevant MBCx pages in this section.", "MBCx findings or standing explanation", "MBCx pages to keep", "Updated MBCx page image"),
    "maintenance": SectionHelp("Check service dates and pages", "Update service calls or vendor pages", "Keep service calls for the reporting month. Include relevant work performed and findings. Leave out prices, legal terms and blank/signature-only pages. Add complete vendor files in this section.", "Maintenance completed this month", "Vendor service pages to keep", "Updated service-page image"),
    "subcontractors": SectionHelp("Check vendor contacts and status", "Update vendors, contacts or MSA status", "Check the vendor, discipline, facility, contact details and agreement status. Keep unchanged rows. You can edit individual contact fields in this section.", "Vendor status notes", "Vendor/contact pages to keep", "Updated vendor-contact page"),
    "water": SectionHelp("Check readings and follow-ups", "Update water-treatment pages or findings", "Check service dates, system names, readings, out-of-limit results and follow-ups. Keep relevant chemical/service pages only. Add this month’s water-treatment files in this section; check the resulting activity wording.", "Water-treatment findings and follow-ups", "Water-treatment pages to keep", "Updated water-treatment page image"),
    "issues": SectionHelp("Review ongoing equipment issues", "Update issues or resolution status", "Check every carried-forward issue. Mark it ongoing, updated or resolved using evidence in this section. Remove a resolved item only after explicitly choosing to do so.", "Equipment issues, actions and current status", "Equipment evidence pictures to keep", "Updated equipment-condition photo"),
    "capital": SectionHelp("Review renewal priorities", "Update priorities or equipment life", "Check equipment condition, replacement priority and known timing. Enter a year, month or date only when known. Carry forward valid items. Client-facing tables must contain no prices or costs.", "Capital renewal notes", "Equipment and renewal pictures to keep", "Updated renewal-item photo"),
    "proposals": SectionHelp("Check proposal status", "Update pending or declined items", "Update scope, vendor and the decision: Pending, Approved, Declined, On hold or Not confirmed. Keep alternative options in the description. Keep supporting work descriptions, and remove every price and commercial/legal-only page from client output.", "Proposal scope and status notes", "Price-free proposal pages to keep", "Updated price-free proposal image"),
    "training": SectionHelp("Review training already entered", "Update training, roles or known hours", "Update the team’s training matrix, then use the form to record training completed this month: in person, virtually or asynchronously. Enter hours only when known.", "Training completed, roles and known hours", "Training pictures to keep", "New training photo"),
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
