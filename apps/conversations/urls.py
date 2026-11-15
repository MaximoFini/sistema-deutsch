from django.urls import path

from . import views

app_name = "ml"
urlpatterns = [
    path("preguntas/", views.QuestionListView.as_view(), name="questions"),
    path("preguntas/respondidas/", views.AnsweredQuestionListView.as_view(), name="questions_answered"),
    path("preguntas/<int:pk>/", views.QuestionDetailView.as_view(), name="question_detail"),
    path("preguntas/<int:pk>/talles/", views.QuestionSizeChartView.as_view(), name="question_size_chart"),
    path("respuestas-guardadas/", views.SavedReplyListView.as_view(), name="saved_replies"),
    path("respuestas-guardadas/<int:pk>/", views.SavedReplyEditView.as_view(), name="saved_reply_edit"),
    path("mensajes/", views.ThreadListView.as_view(), name="threads"),
    path("mensajes/<str:thread_key>/", views.ThreadDetailView.as_view(), name="thread"),
    path(
        "mensajes/<str:thread_key>/adjunto/<str:filename>",
        views.AttachmentView.as_view(),
        name="attachment",
    ),
    path("reclamos/", views.ClaimListView.as_view(), name="claims"),
    path("reclamos/<int:pk>/", views.ClaimDetailView.as_view(), name="claim_detail"),
    path("salud/", views.HealthView.as_view(), name="health"),
    path("salud.xlsx", views.HealthExportView.as_view(), name="health_xlsx"),
    path("contadores/", views.CountersView.as_view(), name="counters"),
]
