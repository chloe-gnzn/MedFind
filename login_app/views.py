from django.contrib import messages
from django.shortcuts import render, redirect

from medfind_project.session_auth import (
    ROLE_HOME, ROLE_LOGIN, SESSION_ID, SESSION_ROLE,
    get_account, login_account, logout_account,
)

from .forms import LoginForm
from .utils import log_activity

LOGIN_PAGES = {
    'user': {
        'heading': 'Log in to your account',
        'register_url': 'register',
        'register_text': "Don’t have an account?",
        'register_label': 'Register Now!',
        'other_url': 'pharmacy_login',
        'other_text': 'Own a pharmacy?',
        'other_label': 'Go to the pharmacy portal',
    },
    'admin': {
        'heading': 'Admin login',
    },
}


def _login(request, role, template='login_template/login.html'):
    # already logged in -> straight to that account's own home screen
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])

    if request.method == 'POST':
        form = LoginForm(request.POST, role=role)
        if form.is_valid():
            account = form.account
            login_account(request, role, account)
            log_activity(role, account.pk, 'login', f'{account.email} logged in.')
            return redirect(ROLE_HOME[role])
    else:
        form = LoginForm(role=role)

    return render(request, template, {
        'form': form,
        'role': role,
        'page': LOGIN_PAGES.get(role, {}),
    })


def login_view(request):
    """General users  ->  /login/"""
    return _login(request, 'user')


def pharmacy_login_view(request):
    """Pharmacies  ->  /pharmacy-portal/login/  (own screen, not shared with users)"""
    return _login(request, 'pharmacy', template='login_template/login_pharmacy.html')


def admin_login_view(request):
    """Admins  ->  /manage/login/"""
    return _login(request, 'admin')


def logout_view(request):
    """Shared by all three roles; sends people back to THEIR login page."""
    role = request.session.get(SESSION_ROLE)
    account_id = request.session.get(SESSION_ID)
    if role and account_id:
        log_activity(role, account_id, 'logout', 'Logged out.')
    logout_account(request)
    messages.info(request, 'You have been logged out.')
    return redirect(ROLE_LOGIN.get(role, 'login'))
