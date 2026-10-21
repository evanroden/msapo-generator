"""Authoritative saved/catalog site choices, shared without importing UI code."""
from dataclasses import replace
import re
from app import contracts
from app.config import FACILITIES
from app.monthly_report_model import Facility


def site_options(contract):
    from app.monthly_report_directory import available_sites, load_directory
    directory = load_directory(contract)
    if contract != contracts.RRH_CONTRACT:
        catalog = tuple(Facility(re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:60], title) for title in contracts.sites_for_contract(contract))
        return available_sites(catalog, directory)
    # Explicit owner-confirmed alias relationship. Never group sites by address
    # or guess regional membership from a title or geographic location.
    result = []
    # Only distinctive, owner-established abbreviations are safe *cover*
    # identity evidence. The general facility catalog also contains city,
    # street and ZIP shorthand; importing all of those as aliases could
    # mistake incidental body/geographic mentions for report membership.
    cover_aliases = {"united_memorial": ("UMMC",), "rochester_general": ("RGH",)}
    for key, value in FACILITIES.items():
        if key == "st_marys" and "unity_specialty" in FACILITIES:
            continue
        aliases = (FACILITIES["st_marys"]["name"],) if key == "unity_specialty" and "st_marys" in FACILITIES else ()
        aliases = (*aliases, *cover_aliases.get(key, ()))
        result.append(Facility(key, value["name"], aliases))
    listed = list(available_sites(result, directory))
    # A real standing directory can replace a catalog facility with a saved
    # site of the same key/title but no aliases. Preserve the owner's saved
    # identifiers and aliases; supplement a DISTINCTIVE shorthand only if
    # exactly one active listed site matches the catalog identity. Never
    # overwrite the standing directory or retarget two duplicate facilities.
    for key, short_names in cover_aliases.items():
        title = FACILITIES[key]["name"].casefold()
        matches = [i for i, site in enumerate(listed)
                   if site.key == key or site.title.casefold() == title]
        if len(matches) != 1:
            continue
        index = matches[0]
        site = listed[index]
        if any(alias.casefold() in
               {other.title.casefold(), *(name.casefold() for name in other.aliases)}
               for i, other in enumerate(listed) if i != index
               for alias in short_names):
            continue
        listed[index] = replace(
            site, aliases=tuple(dict.fromkeys((*site.aliases, *short_names))))
    return tuple(listed)
