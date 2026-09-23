from django.urls import path

from apps.assets.views import DomainImportView

urlpatterns = [
    path("domains/import/", DomainImportView.as_view(), name="domain_import"),
]
