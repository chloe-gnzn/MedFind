from functools import wraps

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect

SESSION_ROLE = 'account_role'
SESSION_ID = 'account_id'

ROLE_HOME = {
    'user': 'home',
    'pharmacy': 'pharmacy_dashboard',
    'admin': 'admin_dashboard',
}

ROLE_LOGIN = {
    'user': 'login',
    'pharmacy': 'pharmacy_login',
    'admin': 'admin_login',
}

ROLE_MODELS = {
    'user': ('home_app', 'User'),
    'pharmacy': ('pharmacy_app', 'Pharmacy'),
    'admin': ('admin_app', 'Admin'),
}


class PasswordMixin:
    """Adds set_password / check_password on top of a `password_hash` column."""

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)


def get_account_model(role):
    app_label, model_name = ROLE_MODELS[role]
    return apps.get_model(app_label, model_name)


def login_account(request, role, account):
    request.session.cycle_key()
    request.session[SESSION_ROLE] = role
    request.session[SESSION_ID] = account.pk


def logout_account(request):
    request.session.flush()


def get_account(request):
    """Return the logged-in account object (or None). Cached per request."""
    if hasattr(request, '_medfind_account'):
        return request._medfind_account

    account = None
    role = request.session.get(SESSION_ROLE)
    pk = request.session.get(SESSION_ID)
    if role in ROLE_MODELS and pk:
        account = get_account_model(role).objects.filter(pk=pk).first()
        if account is not None and role == 'pharmacy' and not account.is_active:
            account = None
    request._medfind_account = account
    return account


def role_required(role):
    """Only let accounts of the given role ('user', 'pharmacy', 'admin') in."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            account = get_account(request)
            if account is None:
                messages.info(request, 'Please log in to continue.')
                return redirect(ROLE_LOGIN[role])
            current_role = request.session.get(SESSION_ROLE)
            if current_role != role:
                return redirect(ROLE_HOME[current_role])
            request.account = account
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def account_context(request):
    """Template context processor: current_account / current_role."""
    account = get_account(request)
    return {
        'current_account': account,
        'current_role': request.session.get(SESSION_ROLE) if account else None,
    }
