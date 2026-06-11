from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("dashboard/", include("dashboard.urls")),
    path("admin/", admin.site.urls),
]
