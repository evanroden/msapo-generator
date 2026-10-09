"""Memory-only LibreOffice profile settings; document/export geometry is unchanged."""
from pathlib import Path


GRAPHIC_MEMORY_BYTES = 48 * 1024 * 1024


def prepare_profile(profile):
    """Configure a newly created per-conversion profile, never a user's profile."""
    profile = Path(profile)
    user = profile / 'user'
    user.mkdir(parents=True, exist_ok=True)
    settings = user / 'registrymodifications.xcu'
    # Cache pressure causes lossless graphic swapping, not image resampling.
    # Do not set PDF quality, font, page, crop, color or transparency options.
    settings.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Cache/GraphicManager">'
        '<prop oor:name="GraphicMemoryLimit" oor:op="fuse"><value>'
        + str(GRAPHIC_MEMORY_BYTES) + '</value></prop>'
        '<prop oor:name="GraphicSwappingEnabled" oor:op="fuse"><value>true</value></prop>'
        '</item></oor:items>', encoding='utf-8')
    return profile.resolve().as_uri()
