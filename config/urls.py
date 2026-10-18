from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.login import LoginForm, PainelLoginForm
from core.views import foto_protegida

admin.site.site_header = 'Oficina – painel do dono'
admin.site.site_title = 'Oficina'
admin.site.index_title = 'Dados e histórico'
admin.site.login_form = PainelLoginForm

urlpatterns = [
    path('painel/', admin.site.urls),
    path('entrar/', auth_views.LoginView.as_view(authentication_form=LoginForm), name='login'),
    path('sair/', auth_views.LogoutView.as_view(), name='logout'),
    path('media/<path:path>', foto_protegida),
    path('', include('core.urls')),
]
