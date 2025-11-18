"""
Core app views.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import connection


class HealthCheckView(APIView):
    """
    Health check endpoint for monitoring system status.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Return system health status.
        """
        health_status = {
            'status': 'healthy',
            'service': 'Universal AI Web Scraper',
            'database': 'connected',
        }

        # Check database connection
        try:
            connection.ensure_connection()
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['database'] = f'disconnected: {str(e)}'
            return Response(health_status, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(health_status, status=status.HTTP_200_OK)
