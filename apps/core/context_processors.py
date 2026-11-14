from django.conf import settings


def panel(request):
    return {"ENVIRONMENT_NAME": settings.ENVIRONMENT_NAME}
