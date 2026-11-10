"""The backend each job gets when Preferences choose none, from the providers that are registered."""

from __future__ import annotations

from typing import TYPE_CHECKING

from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import JOB_DEFAULTS, BackendChoice, Effort, Job

if TYPE_CHECKING:
    from delve.web.app import Registries


def job_providers(registries: Registries) -> list[ProviderCapabilities]:
    """The providers Preferences choose from for jobs: the DM's and the images'."""
    return registries.dm.capabilities() + registries.images.capabilities()


def default_choices(registries: Registries) -> dict[Job, BackendChoice]:
    """For each job, its `JOB_DEFAULTS` choice when that provider is registered, else the first registered provider
    that does it, with its default model, and `auto` effort when it offers that. A job no provider does has no
    default."""
    defaults = {}
    providers = job_providers(registries)
    for job in Job:
        preferred = JOB_DEFAULTS.get(job)
        if preferred is not None and any(caps.id == preferred.provider and job in caps.jobs for caps in providers):
            defaults[job] = preferred
            continue
        caps = next((caps for caps in providers if job in caps.jobs), None)
        if caps is not None:
            effort = Effort.AUTO if Effort.AUTO in caps.efforts else None
            defaults[job] = BackendChoice(caps.id, caps.default_model, effort)
    return defaults
