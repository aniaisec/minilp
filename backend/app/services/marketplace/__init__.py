"""Marketplace bundles (M10, §12) — export/import templates, judge configs, and
project starter kits as shareable, credential-free JSON, plus a local directory
of shipped example bundles. No new tables: §4 has carried every table a bundle
touches since M1."""

from app.services.marketplace.bundle import (
    BUNDLE_KINDS,
    BUNDLE_VERSION,
    MarketplaceError,
    export_judge_config_bundle,
    export_project_bundle,
    export_template_bundle,
    import_bundle,
)
from app.services.marketplace.directory import (
    LocalBundleError,
    list_local_bundles,
    read_local_bundle,
)

__all__ = [
    "BUNDLE_KINDS",
    "BUNDLE_VERSION",
    "LocalBundleError",
    "MarketplaceError",
    "export_judge_config_bundle",
    "export_project_bundle",
    "export_template_bundle",
    "import_bundle",
    "list_local_bundles",
    "read_local_bundle",
]
