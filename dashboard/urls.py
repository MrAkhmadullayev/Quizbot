from django.urls import path

from . import content, views

app_name = "dashboard"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),

    # Testlar
    path("tests/", views.tests, name="tests"),
    path("tests/new/", content.test_form, name="test_new"),
    path("tests/<int:test_id>/", content.test_detail, name="test_detail"),
    path("tests/<int:test_id>/edit/", content.test_form, name="test_edit"),
    path("tests/<int:test_id>/delete/", content.test_delete, name="test_delete"),
    path("tests/<int:test_id>/toggle/", views.test_toggle, name="test_toggle"),

    # Qismlar (SubTest)
    path("subtests/new/", content.subtest_form, name="subtest_new"),
    path("subtests/<int:subtest_id>/", content.subtest_detail, name="subtest_detail"),
    path("subtests/<int:subtest_id>/edit/", content.subtest_form, name="subtest_edit"),
    path("subtests/<int:subtest_id>/delete/", content.subtest_delete, name="subtest_delete"),

    # Savollar (Question) + variantlar
    path("questions/new/", content.question_form, name="question_new"),
    path("questions/<int:question_id>/edit/", content.question_form, name="question_edit"),
    path("questions/<int:question_id>/delete/", content.question_delete, name="question_delete"),

    # Yuklash
    path("upload/", views.upload, name="upload"),
    path("upload/preview/", views.upload_preview, name="upload_preview"),

    # Guruhlar
    path("groups/", views.groups, name="groups"),
    path("groups/new/", views.group_form, name="group_new"),
    path("groups/<int:group_id>/edit/", views.group_form, name="group_edit"),
    path("groups/<int:group_id>/delete/", views.group_delete, name="group_delete"),
    path("users/", views.users, name="users"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
]
