"""Project creation and editing with template + overlap/variant validation (§4, §6.4)."""

from app.services.projects.service import ProjectError, create_project, update_project

__all__ = ["ProjectError", "create_project", "update_project"]
