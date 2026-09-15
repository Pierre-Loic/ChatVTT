from django.urls import path

from . import views

app_name = "game"

urlpatterns = [
    path("", views.board, name="board"),
    path("display/", views.display, name="display"),
    path("api/state", views.api_state, name="api_state"),
    path("api/configure", views.api_configure, name="api_configure"),
    path("api/select-runner", views.api_select_runner, name="api_select_runner"),
    path("api/action/<str:name>", views.api_action, name="api_action"),
    path("api/pedal", views.api_pedal, name="api_pedal"),
]
