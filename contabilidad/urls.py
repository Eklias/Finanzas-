"""
URLs principales del proyecto.
Redirige todas las rutas a la app 'core'.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),  # Todas las rutas van a core
]
#a