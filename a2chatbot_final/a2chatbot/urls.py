from django.contrib import admin
from django.urls import path, re_path
from django.contrib.auth import views as auth_views

import a2chatbot.views as views

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r'^$', views.home, name ='home'),
    re_path(r'^login$', auth_views.LoginView.as_view(template_name='a2chatbot/login.html'), name= 'login'),
    re_path(r'^sendmessage$', views.sendmessage, name ='sendmessage'),

]
