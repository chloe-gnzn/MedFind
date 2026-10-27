from django.shortcuts import redirect, render

from medfind_project.session_auth import ROLE_HOME, SESSION_ROLE, get_account


def landing_view(request):
    """Public landing page for general visitors  ->  /"""
    # anyone already logged in goes straight to their own home screen
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])
    return render(request, 'landing_template/landing.html')
