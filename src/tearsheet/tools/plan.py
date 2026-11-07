"""Work out which Tijori plan the session has, cheaply."""

from tearsheet.core import paths
from tearsheet.core.cache import Cache
from tearsheet.core.session import SessionState, read_session_info
from tearsheet.sources.tijori.client import TijoriClient

# Only company pages state the plan. This one is stable and always present.
REFERENCE_SLUG = "tata-consultancy-services-limited"


async def session_plan(client: TijoriClient, cache: Cache) -> str:
    """Return the plan tier. Without a saved session it's free, with no request."""
    if read_session_info(paths.session_path()).state is not SessionState.SAVED:
        return "free"
    from tearsheet.tools.company import load_company

    data, _ = await load_company(client, cache, REFERENCE_SLUG)
    return data.page.entitlements.plan_tier
