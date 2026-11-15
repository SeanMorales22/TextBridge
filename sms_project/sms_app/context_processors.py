from . import services


def provider_status(request):
    """Tell templates whether the SMS gateway is configured - without exposing any values."""
    return {"provider_configured": services.is_configured()}
